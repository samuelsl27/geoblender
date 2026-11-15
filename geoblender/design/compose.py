# SPDX-License-Identifier: GPL-3.0-or-later
"""La superficie de diseño: el escalonado compuesto con la superficie de partida y las máscaras
(spec 013, T12; HU-013-2; RF-013-29; plan 013 A10, D-9; CE-013-06).

El escalonado (``design.benching``) dice dónde quedaría el banco; la **superficie de diseño** solo
lo aplica donde las máscaras de la 012 lo admiten y deja todo lo demás **exactamente** como estaba
(D-9: el borde de lo prohibido no se suaviza; las transiciones son de R-36):

- **Corte**: ``mín(escalonado, partida)`` solo en las celdas de corte admitido (``cut_allowed``).
- **Relleno**: ``máx(escalonado, partida)`` solo en las de relleno admitido (``fill_allowed``) o de
  la franja de solo relleno (``fill_strip``; es un bit aparte del relleno admitido en la rejilla de
  clases de la 012, ``ClassBit.FILL_STRIP``).
- **Las demás**, la de partida bit a bit: también donde no tiene dato (``NaN``) y donde el
  escalonado no tiene cota (sin envolvente o más allá del alcance), que no mueve nada.

Con esto, la verificación por recinto de la 012 (``reserves.compliance``) da 0 m³ fuera de lo
admitido **por construcción** (CE-013-06): ``design`` no importa ``reserves`` y la prueba lo
comprueba con sus funciones.

Todo es puntual (cada celda depende solo de sus tres valores): quien llama puede partir la
rejilla en bandas de filas sin cambiar ni un bit. Python puro (nivel 8), con numpy; las
entradas no se modifican y el resultado es siempre un array nuevo de ``float64``.
"""

from __future__ import annotations

import numpy as np

from ..gis.masks.access import MaskSet, MaskSource
from ..gis.masks.combine import ClassBit
from .model import BenchSense

__all__ = [
    "admitted",
    "admitted_in",
    "admitted_pair",
    "allowed_cells",
    "compose",
]


def admitted(masks: MaskSet, sense: BenchSense | str) -> np.ndarray:
    """Las celdas donde las máscaras de la 012 admiten el movimiento del ``sense`` pedido (RF-012-13):
    en corte, ``cut_allowed``; en relleno, ``fill_allowed`` o la franja de solo relleno
    (``fill_strip``). Una máscara booleana nueva de la forma de la rejilla de ``masks``."""
    way = BenchSense(sense)
    if way is BenchSense.CUT:
        return masks.cut_allowed()
    return masks.fill_allowed() | masks.fill_strip()


def _admitted_of(classes: np.ndarray, sense: BenchSense | str) -> np.ndarray:
    """:func:`admitted` de unas celdas de la rejilla de clases (``uint16``)."""

    def bit(found: ClassBit) -> np.ndarray:
        return (classes & np.uint16(int(found))) != 0

    if BenchSense(sense) is BenchSense.CUT:
        return bit(ClassBit.CUT_ALLOWED)
    return bit(ClassBit.FILL_ALLOWED) | bit(ClassBit.FILL_STRIP)


def admitted_in(masks: MaskSet | MaskSource, sense: BenchSense | str, window: tuple[slice, slice]
                ) -> np.ndarray:
    """:func:`admitted` **solo en una ventana** de la rejilla (``window``: filas y columnas; spec 015, T37;
    RNF-015-03): lo que ``admitted(masks, sense)[window]`` da, bit a bit, sin construir la máscara de la rejilla entera
    y, con unas máscaras sin cargar (:class:`~geoblender.gis.masks.access.MaskSource`), leyendo de la rejilla de clases
    solo las teselas de la ventana. Una máscara booleana nueva de la forma de la ventana."""
    return _admitted_of(masks.classes_window(window), sense)


def admitted_pair(masks: MaskSet | MaskSource, window: tuple[slice, slice]) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas de ``window`` donde se admite el corte y donde se admite el relleno (:func:`admitted_in` de cada
    sentido), leyendo la ventana de la rejilla de clases **una sola vez**."""
    classes = masks.classes_window(window)
    return _admitted_of(classes, BenchSense.CUT), _admitted_of(classes, BenchSense.FILL)


def allowed_cells(masks: MaskSet, sense: BenchSense | str, domain: np.ndarray | None = None
                  ) -> np.ndarray:
    """Las celdas donde se puede mover la superficie de diseño: :func:`admitted` y, si el dominio de
    trabajo está acotado a unos sectores o a una capa, solo las de ese ``domain`` (la máscara de
    ``DomainSet.mask``: acotar solo resta celdas, nunca las amplía; RF-013-02). ``ValueError`` si
    ``domain`` no es una máscara booleana de la forma de la rejilla."""
    found = admitted(masks, sense)
    if domain is None:
        return found
    bound = np.asarray(domain)
    if bound.dtype != np.bool_ or bound.shape != found.shape:
        raise ValueError(f"el dominio de trabajo es una máscara booleana de la forma de la rejilla "
                         f"{found.shape}, no {bound.dtype} de forma {bound.shape}")
    found &= bound
    return found


def compose(start: np.ndarray, stepped: np.ndarray, allowed: np.ndarray,
            sense: BenchSense | str) -> np.ndarray:
    """La superficie de diseño (RF-013-29, A10): ``mín(stepped, start)`` en corte o
    ``máx(stepped, start)`` en relleno en las celdas ``allowed`` (booleana; :func:`allowed_cells`)
    que tienen cota finita en las dos; en las demás, ``start`` tal cual. Devuelve un array
    ``float64`` nuevo de la forma de ``start``; ninguna entrada se modifica.

    Una forma que no casa, una máscara que no es booleana o un sentido desconocido son errores
    del programa (:class:`ValueError`)."""
    way = BenchSense(sense)
    base = np.asarray(start, dtype=np.float64)
    other = np.asarray(stepped, dtype=np.float64)
    mask = np.asarray(allowed)
    if base.ndim != 2:
        raise ValueError(f"la superficie de partida es una rejilla 2D, no de forma {base.shape}")
    if other.shape != base.shape or mask.shape != base.shape:
        raise ValueError(f"la partida {base.shape}, el escalonado {other.shape} y las celdas "
                         f"admitidas {mask.shape} deben ser de la misma forma")
    if mask.dtype != np.bool_:
        raise ValueError(f"las celdas admitidas son una máscara booleana, no {mask.dtype}")
    result = base.copy()
    pick = np.minimum if way is BenchSense.CUT else np.maximum
    with np.errstate(invalid="ignore"):
        usable = mask & np.isfinite(base) & np.isfinite(other)
    pick(base, other, out=result, where=usable)
    return result
