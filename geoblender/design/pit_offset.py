# SPDX-License-Identifier: GPL-3.0-or-later
"""La distancia por arista de una polilínea de la corta y su desfase (spec 018, T08; HU-018-1; RF-018-06, 08, 09, 10 y 12; plan 018 §5.4
A0 a A2, §5.7 P-4 y P-5, §5.8 H-2).

**La distancia por arista es el único dato del motor** (P-4): :func:`edge_distances` convierte una polilínea cerrada, el perfil, la
roseta, los sectores y los bancos por berma en un array de distancias, una por arista, y :func:`gis.offset.offset_ring_steps` la
desfasa sin saber de minería (principio 3). Cada término es una parte de ese array:

- **El sector** (RF-018-09). Cada arista pertenece al sector que contiene **su punto medio** y se **parte donde cruza el límite** de
  dos sectores (``gis.polygons.crossings``): el tramo que sigue lleva su propia distancia y la unión es la del motor (A3), sin huecos.
  Si dos sectores contienen el punto, manda el primero de la lista; el perímetro (código ``""``) va siempre el último.
- **El azimut de la cara** (RF-018-07). La dirección en que **baja** la cara: en el ascendente la contraria a la normal de desfase y
  en el descendente la misma; en los dos casos, hacia el interior de la polilínea. En ° de 0 a 360 desde el norte, en el sentido de
  las agujas del reloj. Se **suaviza** (P-5): la media, ponderada por la longitud, de las direcciones de la cara de las aristas que
  caen en la ventana ``az_window_m`` centrada en el punto medio de cada arista (la integral exacta, con las aristas que caen a
  medias contando a medias). Sin ventana, el azimut de la propia arista. Si la media se anula (una ventana tan larga como el
  perímetro), la de la propia arista.
- **El rango de la roseta** que contiene el azimut (``[desde, hasta)``), con su α y su B. La roseta es la del sector; si el sector no
  la tiene pero sí perfil propio, la del perfil (un solo rango de α y B del perfil); si tampoco, la de la corta (la roseta base o,
  sin ella, el perfil base). Sin roseta, α y B del perfil (:func:`~design.pit_rose.profile_range`).
- **La distancia.** De la cara, ``n·h/tan α`` con ``n`` los bancos por berma (RF-018-08); en el **primer banco de altura variable**
  (RF-018-12, H-2), ``(z − z_ancla)/tan α`` con la ``z`` de la cresta en la propia arista (la media de sus dos extremos). De la
  berma, ``B``. A cualquiera se le suma el ``extra_m`` de la arista (**el término de la rampa**, que llega de A8 y A9 como un
  argumento).

Lo que **no** hace: simplificar el anillo (A1: lo hace quien llama, con :func:`gis.offset.simplify_ring`, y por eso ``z_m`` y
``extra_m`` van sobre el anillo ya simplificado), leer el proyecto ni escribir nada. Los anillos van en **locales** (ADR-0005) y los
sectores, absolutos, con el ``origin`` que los lleva a los locales. Python puro (nivel 8); no lo importa el arranque.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

from ..core.project.model import Progress
from ..gis.offset import EDGES_PER_STEP, OffsetResult, offset_ring_steps
from ..gis.polygons import crossings, ray_counts
from .model import BenchProfile
from .pit_model import PitSector
from .pit_rose import RoseRange, profile_range

__all__ = [
    "BASE_LABEL",
    "EdgeDistances",
    "PolylineOffset",
    "Step",
    "edge_distances",
    "face_azimuth",
    "offset_polyline_steps",
    "smooth_azimuth",
]

BASE_LABEL = ""
"""La etiqueta de lo que no cae en ningún sector (la corta base)."""

_CUT_MARGIN_M = 1e-9
"""A menos de esto (m) de un extremo de la arista, un corte no se inserta (no parte nada: una arista de longitud 0 rompería el motor)."""
_FLAT = 1e-9
"""Módulo por debajo del cual la media de las direcciones de la cara se toma por nula."""


class Step(StrEnum):
    """Qué lado del banco se desfasa: la ``face`` (de pie a cresta: ``n·h/tan α``) o la ``berm`` (de cresta a pie siguiente: ``B``)."""

    FACE = "face"
    BERM = "berm"


@dataclass(frozen=True, slots=True, eq=False)
class EdgeDistances:
    """La distancia de cada arista, ya partido el anillo en los límites de sector (todo ``(m,)`` salvo ``ring``, de solo lectura).

    ``ring`` es el anillo de **trabajo** ``(m, 2)`` (locales, antihorario, abierto) y ``source_edge`` la arista del anillo de entrada
    (el índice de su vértice inicial) de la que sale cada trozo. ``sector`` es el índice, en la lista dada, del sector de cada arista
    (-1: la corta base) y ``sector_codes`` sus códigos. ``azimuth_deg`` es el azimut de la cara **suavizado** y ``raw_azimuth_deg``
    el de la propia arista; ``face_deg`` (α), ``berm_m`` (B) y ``n_berm`` los del rango que lo contiene y ``distance`` la distancia
    (m) que se le da al motor."""

    ring: np.ndarray
    source_edge: np.ndarray
    sector: np.ndarray
    sector_codes: tuple[str, ...]
    azimuth_deg: np.ndarray
    raw_azimuth_deg: np.ndarray
    face_deg: np.ndarray
    berm_m: np.ndarray
    n_berm: np.ndarray
    distance: np.ndarray

    def __post_init__(self) -> None:
        for name in ("ring", "source_edge", "sector", "azimuth_deg", "raw_azimuth_deg", "face_deg", "berm_m", "n_berm", "distance"):
            view = getattr(self, name).view()
            view.flags.writeable = False
            object.__setattr__(self, name, view)

    def label_of(self, edge: int) -> str:
        """El código del sector de la arista ``edge`` (:data:`BASE_LABEL` si es de la corta base)."""
        index = int(self.sector[edge])
        return BASE_LABEL if index < 0 else self.sector_codes[index]


@dataclass(frozen=True, slots=True, eq=False)
class PolylineOffset:
    """El desfase de una polilínea (:func:`offset_polyline_steps`): el ``result`` del motor, con sus aristas de origen en el anillo
    de trabajo de ``edges``; ``sector_of_vertex`` (un array por anillo y después uno por hueco, como ``result.source_edge_of_vertex``)
    con el índice en ``sector_labels`` del sector de cada vértice (0: la corta base; ``i + 1``: el sector ``i`` de la lista dada) y
    la ``zone`` que se le dio a la polilínea."""

    result: OffsetResult
    edges: EdgeDistances
    sector_labels: tuple[str, ...]
    sector_of_vertex: tuple[np.ndarray, ...]
    zone: str = ""


# --- El azimut de la cara ---------------------------------------------------------------------------------------------


def _checked_ring(ring: object) -> np.ndarray:
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or points.shape[0] < 3:
        raise ValueError(f"El anillo es un array (k, 2) con al menos tres vértices, no de forma {points.shape}")
    if not np.isfinite(points).all():
        raise ValueError("El anillo tiene coordenadas no finitas")
    x, y = points[:, 0], points[:, 1]
    if not 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) > 0.0:
        raise ValueError("El anillo debe ser antihorario y con área")
    along = np.roll(points, -1, axis=0) - points
    if np.any(np.hypot(along[:, 0], along[:, 1]) == 0.0):
        raise ValueError("El anillo tiene una arista de longitud 0 (simplifícalo antes)")
    return points


def _face_direction(ring: np.ndarray, side: int) -> tuple[np.ndarray, np.ndarray]:
    """La dirección unitaria en que baja la cara de cada arista y su longitud. En el ascendente (``side = +1``), la contraria a la
    normal de desfase (la derecha de la marcha, hacia fuera); en el descendente (``side = -1``), la misma (hacia dentro)."""
    if side not in (1, -1):
        raise ValueError(f"El lado es +1 (ascendente) o -1 (descendente), no {side!r}")
    along = np.roll(ring, -1, axis=0) - ring
    length = np.hypot(along[:, 0], along[:, 1])
    tangent = along / length[:, None]
    offset_normal = side * np.column_stack([tangent[:, 1], -tangent[:, 0]])
    return (-offset_normal if side > 0 else offset_normal), length


def _azimuth(direction: np.ndarray) -> np.ndarray:
    """El azimut (°, de 0 a 360 desde el norte, en el sentido de las agujas del reloj) de cada dirección."""
    return np.degrees(np.arctan2(direction[:, 0], direction[:, 1])) % 360.0


def face_azimuth(ring: object, side: int = 1) -> np.ndarray:
    """El azimut de la cara (°) de cada arista de ``ring`` (antihorario, abierto), **sin suavizar** (RF-018-07)."""
    direction, _ = _face_direction(_checked_ring(ring), side)
    return _azimuth(direction)


def smooth_azimuth(ring: object, side: int = 1, window_m: float | None = None) -> np.ndarray:
    """El azimut de la cara (°) de cada arista **suavizado** sobre una ventana de ``window_m`` m de longitud (P-5; ver el módulo).
    Sin ventana (``None`` o 0), el de la propia arista. ``ValueError`` si la ventana es negativa o no es finita."""
    points = _checked_ring(ring)
    direction, length = _face_direction(points, side)
    if window_m is None or window_m == 0.0:
        return _azimuth(direction)
    if not math.isfinite(window_m) or window_m < 0.0:
        raise ValueError(f"La ventana del azimut es una longitud finita no negativa, no {window_m!r}")
    start = np.concatenate([[0.0], np.cumsum(length)])
    perimeter = float(start[-1])
    carried = np.concatenate([np.zeros((1, 2)), np.cumsum(length[:, None] * direction, axis=0)])
    # La integral acumulada de la dirección es periódica (la suma de las normales ponderadas de un anillo cerrado es 0).

    def integral(s: np.ndarray) -> np.ndarray:
        wrapped = np.mod(s, perimeter)
        edge = np.clip(np.searchsorted(start, wrapped, side="right") - 1, 0, len(length) - 1)
        return carried[edge] + (wrapped - start[edge])[:, None] * direction[edge]

    middle = start[:-1] + 0.5 * length
    mean = (integral(middle + 0.5 * window_m) - integral(middle - 0.5 * window_m)) / window_m
    flat = np.hypot(mean[:, 0], mean[:, 1]) < _FLAT
    return _azimuth(np.where(flat[:, None], direction, mean))


# --- Los sectores -----------------------------------------------------------------------------------------------------


def _sector_order(sectors: Sequence[PitSector]) -> list[int]:
    return sorted(range(len(sectors)), key=lambda index: sectors[index].code == "")


def _boundary(sectors: Sequence[PitSector], origin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    starts: list[np.ndarray] = []
    ends: list[np.ndarray] = []
    for sector in sectors:
        for part in sector.parts:
            for ring in part:
                local = np.asarray(ring, dtype=np.float64) - origin
                starts.append(local)
                ends.append(np.roll(local, -1, axis=0))
    if not starts:
        return np.empty((0, 2)), np.empty((0, 2))
    return np.concatenate(starts), np.concatenate(ends)


def _split(ring: np.ndarray, sectors: Sequence[PitSector], origin: np.ndarray
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """El anillo partido donde sus aristas cruzan el límite de un sector: los vértices, la arista de entrada de la que sale cada uno y
    la posición de cada uno en ella (0 para los vértices originales)."""
    count = len(ring)
    owner = np.arange(count)
    where = np.zeros(count)
    points = ring
    if sectors:
        qa, qb = _boundary(sectors, origin)
        if len(qa):
            pa, pb = ring, np.roll(ring, -1, axis=0)
            edge, _, t, _, cut = crossings(pa, pb, qa, qb)
            if edge.size:
                span = np.hypot(*(pb[edge] - pa[edge]).T)
                keep = (t * span > _CUT_MARGIN_M) & ((1.0 - t) * span > _CUT_MARGIN_M)
                edge, t, cut = edge[keep], t[keep], cut[keep]
                order = np.lexsort((t, edge))
                edge, t, cut = edge[order], t[order], cut[order]
                if edge.size:
                    first = np.ones(len(edge), dtype=bool)
                    first[1:] = (edge[1:] != edge[:-1]) | ((t[1:] - t[:-1]) * span[keep][order][1:] > _CUT_MARGIN_M)
                    edge, t, cut = edge[first], t[first], cut[first]
                    owner = np.concatenate([owner, edge])
                    where = np.concatenate([where, t])
                    points = np.concatenate([ring, cut])
    order = np.lexsort((where, owner))
    return points[order], owner[order], where[order]


def _containing(mid: np.ndarray, sectors: Sequence[PitSector], origin: np.ndarray) -> np.ndarray:
    """El índice del sector que contiene cada punto (-1: ninguno); manda el primero y el perímetro va el último."""
    found = np.full(len(mid), -1, dtype=np.int64)
    for index in _sector_order(sectors):
        free = np.flatnonzero(found < 0)
        if not free.size:
            break
        inside = np.zeros(len(free), dtype=bool)
        for part in sectors[index].parts:
            rings = [np.asarray(ring, dtype=np.float64) - origin for ring in part]
            a = np.concatenate(rings)
            b = np.concatenate([np.roll(ring, -1, axis=0) for ring in rings])
            inside |= ray_counts(mid[free], a, b)[:, 0] % 2 == 1
        found[free[inside]] = index
    return found


# --- La distancia por arista ------------------------------------------------------------------------------------------


def _ranges_of(sector: PitSector | None, profile: BenchProfile, base_rose: Sequence[RoseRange] | None) -> Sequence[RoseRange]:
    if sector is not None and sector.rose is not None:
        return sector.rose
    if sector is not None and sector.profile is not None:
        return (profile_range(profile.face_deg, profile.berm_m),)
    if base_rose is not None:
        return base_rose
    return (profile_range(profile.face_deg, profile.berm_m),)


def edge_distances(ring: object, *, step: Step | str, side: int = 1, profile: BenchProfile | None = None,
                   rose: Sequence[RoseRange] | None = None, n_berm: int = 1, sectors: Sequence[PitSector] = (),
                   origin: Sequence[float] = (0.0, 0.0), az_window_m: float | None = None,
                   z_m: object | None = None, anchor_m: float | None = None, extra_m: object | None = None) -> EdgeDistances:
    """La distancia de cada arista del anillo ``ring`` (antihorario, abierto, locales, sin aristas de longitud 0) para el lado ``step``
    del banco (:class:`Step`), con ``side`` ``+1`` (ascendente: hacia fuera) o ``-1`` (descendente: hacia dentro). ``profile`` es el
    perfil base (de él salen α, B y la altura ``h``; ``None`` solo si todo cae en sectores con perfil propio), ``rose`` la roseta base
    (``None``: α y B del perfil) y ``n_berm`` los bancos por berma de la corta (RF-018-08). ``sectors`` (:class:`~design.pit_model.PitSector`,
    absolutos) y su ``origin`` dan la partición (RF-018-09); ``az_window_m`` suaviza el azimut (P-5). ``z_m`` (``(k,)``, la cota de cada
    vértice de ``ring``) y ``anchor_m`` hacen de la cara un **primer banco de altura variable** (RF-018-12, H-2; solo ``face``: la
    distancia es ``(z − z_ancla)/tan α``, sin ``n``). ``extra_m`` (``(k,)``, por arista de ``ring``) se suma a la distancia: el
    término de la rampa (A8, A9). ``ValueError`` si algo no vale: son errores del programa, que la preparación ya comprobó."""
    points = _checked_ring(ring)
    kind = Step(step)
    count = len(points)
    if (z_m is None) != (anchor_m is None):
        raise ValueError("El primer banco de altura variable lleva sus cotas (z_m) y su ancla (anchor_m) a la vez")
    if z_m is not None and kind is not Step.FACE:
        raise ValueError("La altura variable es de la cara, no de la berma")
    if isinstance(n_berm, bool) or not isinstance(n_berm, int) or n_berm < 1:
        raise ValueError(f"Los bancos por berma son un entero ≥ 1, no {n_berm!r}")
    z_in = None
    if z_m is not None:
        z_in = np.asarray(z_m, dtype=np.float64)
        if z_in.shape != (count,) or not np.isfinite(z_in).all():
            raise ValueError(f"Las cotas son un array finito ({count},), no de forma {z_in.shape}")
    extra_in = np.zeros(count)
    if extra_m is not None:
        extra_in = np.asarray(extra_m, dtype=np.float64)
        if extra_in.shape != (count,) or not np.isfinite(extra_in).all():
            raise ValueError(f"El término de la rampa es un array finito ({count},), no {extra_in.shape}")
    frame = np.asarray(origin, dtype=np.float64)
    if frame.shape != (2,):
        raise ValueError(f"El origen son dos coordenadas, no {frame.shape}")

    work, owner, where = _split(points, sectors, frame)
    total = len(work)
    following = np.roll(work, -1, axis=0)
    mid = 0.5 * (work + following)
    found = _containing(mid, sectors, frame) if sectors else np.full(total, -1, dtype=np.int64)

    raw = face_azimuth(work, side)
    azimuth = smooth_azimuth(work, side, az_window_m)

    face = np.empty(total)
    berm = np.empty(total)
    height = np.empty(total)
    levels = np.ones(total, dtype=np.int64)
    for index in np.unique(found):
        mask = found == index
        sector = None if index < 0 else sectors[int(index)]
        chosen = None if sector is None else sector.profile
        used = chosen if chosen is not None else profile
        if used is None:
            where_ = "la corta base" if sector is None else f"el sector «{sector.code}»"
            raise ValueError(f"Sin perfil de banco para {where_}: ni propio ni base")
        ranges = sorted(_ranges_of(sector, used, rose), key=lambda item: item.from_deg)
        starts = np.array([item.from_deg for item in ranges])
        picked = np.clip(np.searchsorted(starts, azimuth[mask], side="right") - 1, 0, len(ranges) - 1)
        face[mask] = np.array([item.face_deg for item in ranges])[picked]
        berm[mask] = np.array([item.berm_m for item in ranges])[picked]
        height[mask] = used.height_m
        levels[mask] = n_berm if sector is None or sector.n_berm is None else sector.n_berm

    if kind is Step.BERM:
        distance = berm.copy()
    elif z_in is not None:
        z_work = z_in[owner] + where * (z_in[(owner + 1) % count] - z_in[owner])
        drop = 0.5 * (z_work + np.roll(z_work, -1)) - float(anchor_m)  # type: ignore[arg-type]
        if np.any(drop < -1e-9):
            raise ValueError("Hay cresta por debajo del ancla del primer banco: el ancla es la primera por debajo del mínimo (H-2)")
        distance = np.maximum(drop, 0.0) / np.tan(np.radians(face))
    else:
        distance = levels * height / np.tan(np.radians(face))
    distance = distance + extra_in[owner]
    if np.any(distance < 0.0):
        raise ValueError("El término de la rampa deja una distancia negativa (más que la base de la arista)")
    return EdgeDistances(work, owner, found, tuple(item.code for item in sectors), azimuth, raw, face, berm, levels, distance)


# --- El desfase de una polilínea --------------------------------------------------------------------------------------


def offset_polyline_steps(ring: object, *, step: Step | str, side: int = 1, tol: float, corner: str = "round",
                          simplify_m: float = 0.0, zone: str = "", edges_per_step: int = EDGES_PER_STEP,
                          profile: BenchProfile | None = None, rose: Sequence[RoseRange] | None = None, n_berm: int = 1,
                          sectors: Sequence[PitSector] = (), origin: Sequence[float] = (0.0, 0.0),
                          az_window_m: float | None = None, z_m: object | None = None, anchor_m: float | None = None,
                          extra_m: object | None = None) -> Iterator[Progress]:
    """Los pasos del desfase de una polilínea con su zona y su sector por tramo (A2 + A3 + A4): la distancia de cada arista
    (:func:`edge_distances`, con los mismos argumentos), el desfase del motor (:func:`gis.offset.offset_ring_steps`, que cede un
    ``Progress`` cada ≈ ``edges_per_step`` aristas) y, en el último, un :class:`PolylineOffset` en ``result``. ``zone`` es la de la
    polilínea de origen (se devuelve tal cual). Cerrar el iterador cancela sin dejar nada."""
    found = edge_distances(ring, step=step, side=side, profile=profile, rose=rose, n_berm=n_berm, sectors=sectors, origin=origin,
                           az_window_m=az_window_m, z_m=z_m, anchor_m=anchor_m, extra_m=extra_m)
    labels = (BASE_LABEL, *found.sector_codes)
    for progress in offset_ring_steps(found.ring, found.distance, side, tol=tol, corner=corner, simplify_m=simplify_m,
                                      edges_per_step=edges_per_step):
        if progress.result is None:
            yield progress
            continue
        result = progress.result
        assert isinstance(result, OffsetResult)
        by_vertex = tuple(found.sector[edges] + 1 for edges in result.source_edge_of_vertex)
        yield replace(progress, result=PolylineOffset(result, found, labels, by_vertex, zone))
