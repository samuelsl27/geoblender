# SPDX-License-Identifier: GPL-3.0-or-later
"""Análisis de la medida de la barra superior en la GUI (spec 003, T19; RF-003-10;
RNF-003-01, RNF-003-03; BS §2.2 y §2.3; AR §3.2 y §3.3).

``tools/inblender/measure_topbar.py`` captura, dentro de Blender con interfaz, la ventana
con la barra en cada nivel (A–E), escala (1,0 y 1,25) e idioma, y la fila 2 de la Vista 3D
en cada modo; reduce cada franja de la captura a una lista de columnas con contenido
(``True`` donde algún píxel se aparta del fondo) y cronometra el redibujo. Este módulo,
puro, hace el resto (lo prueba ``tests/unit/tools/test_measure_topbar.py``):

- :func:`split`: dónde acaba la parte izquierda de la barra, dónde empieza el bloque
  derecho de Blender y cuánto queda libre entre los dos (el mismo método que BS §2.2: el
  hueco mayor entre las columnas con contenido);
- :func:`native_px`: lo que ocupan los ajustes nativos de la herramienta en la fila 2 (el
  contenido sin el hueco central);
- :func:`fit_topbar_constants`: las constantes del modelo de BS §2.3 (``menu_pad``,
  ``fixed_b``, ``icon_menu``, ``version_compact`` y ``title_icon``) que reproducen las
  anchuras medidas de los cinco niveles, con los títulos medidos con ``blf``;
- :func:`right_block_px`: el bloque derecho medido (a escala 1,0) y
  :func:`suggested_right_block`, con el margen de BS §2.3 (333 medidos → 340);
- :func:`checks`: RNF-003-01 (B ≥ 150 px libres a 1,0 y C ≥ 24 px a 1,25, en los dos
  idiomas) y RNF-003-03 (redibujo en modo Geoblender ≤ el de modo Blender + 1 ms).

Todas las anchuras de entrada van en px reales (a la escala de la captura); las constantes
que devuelve, a escala 1,0, como las de ``bl/compat.py``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

LEVELS = ("A", "B", "C", "D", "E")
MIN_GAP_PX = 12  # un hueco menor no separa dos bloques (el espacio entre botones)
RIGHT_BLOCK_MARGIN_PX = 7  # BS §2.3: 333 px medidos → 340 en el modelo
FREE_B_MIN_PX = 150.0  # RNF-003-01
FREE_C_MIN_PX = 24.0
REDRAW_MARGIN_MS = 1.0  # RNF-003-03


@dataclass(frozen=True)
class Split:
    """Una franja de la barra partida por su hueco mayor: primera columna con contenido,
    fin de la parte izquierda, inicio del bloque derecho y fin del contenido (los finales,
    exclusivos)."""

    first: int
    left_end: int
    right_start: int
    last: int

    @property
    def left_px(self) -> int:
        """Anchura de la parte izquierda."""
        return self.left_end - self.first

    @property
    def free_px(self) -> int:
        """El hueco entre la parte izquierda y el bloque derecho."""
        return self.right_start - self.left_end

    @property
    def right_px(self) -> int:
        """Anchura del bloque derecho hasta su última columna con contenido."""
        return self.last - self.right_start


def runs(columns: Sequence[bool], *, min_gap: int = MIN_GAP_PX) -> list[tuple[int, int]]:
    """Los tramos ``(inicio, fin)`` (fin exclusivo) de columnas con contenido, uniendo los
    separados por menos de ``min_gap`` columnas vacías."""
    found: list[tuple[int, int]] = []
    start: int | None = None
    for index, filled in enumerate([*columns, False]):
        if filled and start is None:
            start = index
        elif not filled and start is not None:
            if found and start - found[-1][1] < min_gap:
                found[-1] = (found[-1][0], index)
            else:
                found.append((start, index))
            start = None
    return found


def split(columns: Sequence[bool], *, min_gap: int = MIN_GAP_PX) -> Split | None:
    """La franja partida por el hueco mayor entre tramos; con un solo tramo, el bloque
    derecho empieza donde acaba la franja (sin hueco medible). ``None`` si está vacía."""
    found = runs(columns, min_gap=min_gap)
    if not found:
        return None
    first, last = found[0][0], found[-1][1]
    if len(found) == 1:
        return Split(first, last, len(columns), last)
    gaps = [(found[i + 1][0] - found[i][1], i) for i in range(len(found) - 1)]
    _size, index = max(gaps)
    return Split(first, found[index][1], found[index + 1][0], last)


def native_px(columns: Sequence[bool], *, min_gap: int = MIN_GAP_PX) -> int:
    """Lo que ocupa el contenido de una fila sin su hueco mayor: los ajustes nativos de la
    herramienta a la izquierda y «Opciones» a la derecha (AR §3.2)."""
    parts = split(columns, min_gap=min_gap)
    if parts is None:
        return 0
    if parts.right_start >= len(columns):
        return parts.left_px
    return parts.left_px + parts.right_px


@dataclass(frozen=True)
class Sample:
    """La anchura medida de la parte izquierda en cada nivel (px reales) para un idioma y
    una escala."""

    language: str
    scale: float
    widths: Mapping[str, float]


def _fit_one(widths: Mapping[str, float], titles: Mapping[str, float], *, flow: Sequence[str],
             tools: str, help_: str, geoblender: str) -> dict[str, float]:
    """Las constantes que reproducen exactamente las cinco anchuras (a escala 1,0) del
    modelo de BS §2.3 (``core.catalog.width.topbar_width``):

    A = T + 13·pad + 12·ti + F · B = T + 13·pad + F ·
    C = T_flujo + 11·pad + 2·ic + F − vc · D = 13·ic + F − vc · E = g + pad + F − vc."""
    t_flow = sum(titles[menu] for menu in flow)
    t_tools, t_help, t_geoblender = titles[tools], titles[help_], titles[geoblender]
    n = len(flow)
    a, b, c, d, e = (widths[level] for level in LEVELS)
    title_icon = (a - b) / (n + 1)
    pad_minus_icon = (c - d - t_flow) / n
    icon_times = d - e + t_geoblender  # (n + 2)·ic − pad
    icon_menu = (pad_minus_icon + icon_times) / (n + 1)
    menu_pad = pad_minus_icon + icon_menu
    fixed_b = b - (t_flow + t_tools + t_help) - (n + 2) * menu_pad
    version_compact = b - c - t_tools - t_help - 2 * menu_pad + 2 * icon_menu
    return {"menu_pad": menu_pad, "fixed_b": fixed_b, "icon_menu": icon_menu,
            "version_compact": version_compact, "title_icon": title_icon}


def fit_topbar_constants(samples: Sequence[Sample],
                         titles: Mapping[str, Mapping[str, float]], *, flow: Sequence[str],
                         tools: str, help_: str, geoblender: str) -> dict[str, float]:
    """La media, sobre las muestras con los cinco niveles, de las constantes del modelo a
    escala 1,0. ``titles``: anchos ``blf`` a escala 1,0 por idioma y por clase de menú;
    ``flow``: los 11 menús del flujo. Sin ninguna muestra completa, vacío."""
    fits = []
    for sample in samples:
        if not all(level in sample.widths for level in LEVELS):
            continue
        widths = {level: sample.widths[level] / sample.scale for level in LEVELS}
        fits.append(_fit_one(widths, titles[sample.language], flow=flow, tools=tools,
                             help_=help_, geoblender=geoblender))
    if not fits:
        return {}
    return {key: sum(fit[key] for fit in fits) / len(fits) for key in fits[0]}


def right_block_px(measures: Sequence[tuple[float, float, float]]) -> float:
    """El bloque derecho de Blender a escala 1,0: el mayor ``(ancho de la región − inicio
    del bloque) / escala`` de las medidas ``(ancho, inicio, escala)``."""
    return max(((width - start) / scale for width, start, scale in measures), default=0.0)


def suggested_right_block(measured_px: float) -> float:
    """La constante ``right_block`` del modelo: lo medido, redondeado hacia arriba, más el
    margen de BS §2.3."""
    return float(math.ceil(measured_px) + RIGHT_BLOCK_MARGIN_PX)


def redraw_ms(seconds: float, iterations: int) -> float:
    """Milisegundos por redibujo."""
    return 1000.0 * seconds / iterations if iterations else 0.0


def checks(free: Mapping[tuple[str, float, str], float], *, geoblender_ms: float | None,
           blender_ms: float | None) -> dict[str, bool]:
    """RNF-003-01 con lo medido (``free[(idioma, escala, nivel)]`` en px reales a 1920 px)
    y RNF-003-03 con el redibujo; una medida que falta, falsa."""
    result: dict[str, bool] = {}
    for language in ("es", "en"):
        b = free.get((language, 1.0, "B"))
        c = free.get((language, 1.25, "C"))
        result[f"RNF-003-01 B {language} 1.0 >= 150"] = b is not None and b >= FREE_B_MIN_PX
        result[f"RNF-003-01 C {language} 1.25 >= 24"] = c is not None and c >= FREE_C_MIN_PX
    result["RNF-003-03 redibujo <= Blender + 1 ms"] = (
        geoblender_ms is not None and blender_ms is not None
        and geoblender_ms <= blender_ms + REDRAW_MARGIN_MS
    )
    return result
