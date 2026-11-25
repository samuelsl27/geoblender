# SPDX-License-Identifier: GPL-3.0-or-later
"""El modelo de alturas de los diálogos (spec 019, T26; RF-019-20; plan 019 A7; UI-01).

Python puro: ni ``bpy`` ni el ``bl/`` real. El *layout* falso (:class:`tests.support.fake_layout.FakeLayout`) no ve
anchos, solapes ni recortes; lo que mide es un **modelo**, calibrado en la 018 con el H3 (el diálogo de «Nueva corta…»
medía ≈ 1.000 px en pantalla y el modelo dio lo mismo): 25 px por campo, 20 por etiqueta, 30 por botón, 10 por caja
y 100 de título y botones (los de confirmar y cancelar). Un diálogo cabe cuando su altura, a la escala efectiva de la
interfaz, no pasa de la ventana (1001 px), es decir, cuando ``altura × escala ≤ 1001``; y su ancho, cuando
``ancho × escala ≤ 1920``. Las escalas son las tres de la 003: 1,0, 1,25 y 1,5556.

Lo que el modelo no ve (cuadros desplegables, listas que crecen con el proyecto, el ancho real de una etiqueta) lo
confirma el H3 de la 019. :func:`height` es **el** modelo: ``tests/blender/milestone_pit_ops`` lo usa también.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

FIELD_PX = 25
LABEL_PX = 20
BUTTON_PX = 30
BOX_PX = 10
CHROME_PX = 100
WINDOW_PX = 1001
WINDOW_WIDTH_PX = 1920
SCALES: tuple[float, ...] = (1.0, 1.25, 1.5556)

# Los métodos del *layout* que cuentan como un campo (una fila de 25 px).
FIELD_KINDS = ("prop", "prop_search", "prop_enum")


def height(shown: Any) -> int:
    """Lo que mide, en píxeles a escala 1,0, el diálogo dibujado en ``shown`` (un ``FakeLayout``)."""
    items = shown.items
    kinds = [item.kind for item in items]
    boxes = len({
        id(item.layout) for item in items
        if item.layout is not None and item.layout.parent is not None and item.layout.parent.parent is None
        and item.kind != "operator"
    })
    return (sum(kinds.count(kind) for kind in FIELD_KINDS) * FIELD_PX + kinds.count("label") * LABEL_PX
            + kinds.count("operator") * BUTTON_PX + boxes * BOX_PX + CHROME_PX)


def height_of_fields(count: int) -> int:
    """Lo que mide un diálogo de ``count`` campos sueltos (para los diálogos sin ``draw``, que Blender dibuja solo)."""
    return count * FIELD_PX + CHROME_PX


@dataclass(frozen=True)
class Fit:
    """Si un diálogo de ``height_px`` × ``width_px`` cabe a ``scale`` en la ventana de 1920 × 1001."""

    scale: float
    height_px: float
    width_px: float
    fits_height: bool
    fits_width: bool

    @property
    def fits(self) -> bool:
        return self.fits_height and self.fits_width


def fit(height_px: float, width_px: float = 0.0, scale: float = 1.0) -> Fit:
    """:class:`Fit` de un diálogo a una escala efectiva."""
    return Fit(scale, height_px, width_px, height_px * scale <= WINDOW_PX, width_px * scale <= WINDOW_WIDTH_PX)


def misfits(height_px: float, width_px: float = 0.0, scales: Iterable[float] = SCALES) -> list[Fit]:
    """Las escalas a las que el diálogo no cabe (vacío: cabe a todas)."""
    return [result for result in (fit(height_px, width_px, scale) for scale in scales) if not result.fits]


def verdict(height_px: float, width_px: float = 0.0) -> str:
    """``"fits"``, ``"height"``, ``"width"`` o ``"height+width"``: lo que no cabe a alguna de las tres escalas."""
    failing = misfits(height_px, width_px)
    parts = [name for name, bad in (("height", any(not f.fits_height for f in failing)),
                                    ("width", any(not f.fits_width for f in failing))) if bad]
    return "+".join(parts) or "fits"
