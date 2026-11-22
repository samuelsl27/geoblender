# SPDX-License-Identifier: GPL-3.0-or-later
"""La colocación sin solapes de los nombres de una vista previa (spec 017, T50; hallazgo H3-3 del H3; HU-017-1; RF-017-26, RF-015-26).

Los nombres de una vista previa se escriben junto a su sitio, en píxeles de la región de la Vista 3D. Con la vista lejos (520 m de distancia en el H3) los de un origen y su primer tramo, o los de
un tramo de 1 m y el siguiente, caen unos sobre otros y no se leen. :func:`place_labels` dice **cuáles se dibujan**: se ponen primero los de más rango (los que no tienen rango, siempre) y, entre
los del mismo rango, el primero; el que cae sobre otro ya puesto —sus cajas, de la altura del texto, se solapan: queda a menos de una altura de texto de él y a lo ancho del otro— se salta. Lo que
se salta no se pierde: sigue en el resumen de la vista previa.

Es una función **pura** (listas de números, sin ``bpy`` ni ``blf``: quien la llama mide los textos), de dominio, para probarla con posiciones a mano. No cambia ninguna cifra ni ningún cálculo: solo
decide qué nombre se escribe.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["place_labels"]


def place_labels(points: Sequence[tuple[float, float]], widths: Sequence[float], height: float,
                 ranks: Sequence[int | None] | None = None) -> list[int]:
    """Los índices (de menor a mayor) de los nombres que se dibujan de los ``points`` (``(x, y)`` px: la esquina inferior izquierda de la caja de cada texto) de ``widths`` px de ancho y ``height`` px
    de alto, con su rango en ``ranks`` (``None`` en todos si no se da).

    Se ponen primero **los que no tienen rango** (``None``: nunca se saltan, aunque se solapen entre sí) y después los de más rango a menos; entre iguales, el primero (el orden de ``points``). Un
    nombre con rango se salta si su caja se solapa con la de otro ya puesto: la distancia vertical entre los dos es **menor que una altura de texto** y a la vez los intervalos horizontales de los dos
    se montan (dos cajas que solo se tocan no se solapan). ``ValueError`` (error del programa) si las listas no son del mismo largo o la altura no es un número positivo."""
    count = len(points)
    given = [None] * count if ranks is None else list(ranks)
    if len(widths) != count or len(given) != count:
        raise ValueError(f"los sitios, los anchos y los rangos son del mismo largo, no {count}, {len(widths)} y {len(given)}")
    if not (isinstance(height, int | float) and math.isfinite(height) and height > 0.0):
        raise ValueError(f"la altura de un texto es un número positivo, no {height!r}")
    order = sorted(range(count), key=lambda index: (given[index] is not None, -(given[index] or 0), index))
    placed: list[tuple[float, float, float]] = []  # (izquierda, derecha, y) de lo ya puesto
    kept: list[int] = []
    for index in order:
        x, y = float(points[index][0]), float(points[index][1])
        right = x + float(widths[index])
        free = given[index] is None or not any(abs(y - other_y) < height and x < other_right and other_left < right for other_left, other_right, other_y in placed)
        if free:
            placed.append((x, right, y))
            kept.append(index)
    return sorted(kept)
