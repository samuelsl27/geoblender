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
  hueco mayor entre las columnas con contenido); :func:`split_at`, lo mismo con el borde
  de la región de ``draw_left`` conocido (en Blender 5.2 el bloque derecho es otra región;
  convergencia, T42);
- :func:`native_px`: lo que ocupan los ajustes nativos de la herramienta en la fila 2 (el
  contenido sin el hueco central);
- :func:`fit_topbar_constants`: las constantes del modelo de BS §2.3 (``menu_pad``,
  ``fixed_b``, ``icon_menu``, ``version_compact`` y ``title_icon``) que mejor reproducen,
  por mínimos cuadrados, las anchuras medidas de los niveles que caben, con los títulos
  medidos con ``blf``;
- :func:`right_block_px`: el bloque derecho medido (a escala 1,0) y
  :func:`suggested_right_block`, con el margen de BS §2.3 (333 medidos → 340);
  :func:`right_region_px`, la región derecha de la barra a escala 1,0 (T42);
- :func:`best_level`: el nivel más informativo que cabe según lo medido (RF-003-10);
- :func:`checks`: RNF-003-01 (B ≥ 150 px libres a 1,0 y C ≥ 24 px a 1,25, en los dos
  idiomas), el nivel del automático (BS §3 y RF-003-10) y RNF-003-03 (redibujo en modo
  Geoblender ≤ el de modo Blender + 1 ms).

Todas las anchuras de entrada van en px reales (a la escala de la captura); las constantes
que devuelve, a escala 1,0, como las de ``bl/compat.py``. **La escala es la efectiva**
(``preferences.system.ui_scale``: la «Escala de resolución» por la del sistema operativo;
en una pantalla con Windows al 125 %, la efectiva 1,0 es la de resolución 0,8; T42).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
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


def split_at(columns: Sequence[bool], boundary: int, *,
             min_gap: int = MIN_GAP_PX) -> Split | None:
    """La franja partida por ``boundary``, el borde derecho de la región de ``draw_left``:
    la parte izquierda es el contenido antes del borde y el bloque derecho, el de después
    (sin él, empieza donde acaba la franja). ``None`` si no hay nada antes del borde."""
    left = runs(columns[:boundary], min_gap=min_gap)
    if not left:
        return None
    right = [(start + boundary, end + boundary)
             for start, end in runs(columns[boundary:], min_gap=min_gap)]
    if not right:
        return Split(left[0][0], left[-1][1], len(columns), left[-1][1])
    return Split(left[0][0], left[-1][1], right[0][0], right[-1][1])


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


UNKNOWNS = ("menu_pad", "fixed_b", "icon_menu", "version_compact", "title_icon")


def _equation(level: str, titles: Mapping[str, float], *, flow: Sequence[str], tools: str,
              help_: str, geoblender: str) -> tuple[tuple[float, ...], float]:
    """Los coeficientes de :data:`UNKNOWNS` y la parte conocida (los títulos) de la anchura
    de ``level`` a escala 1,0 en el modelo de BS §2.3 (``core.catalog.width.topbar_width``):

    A = T + 13·pad + 12·ti + F · B = T + 13·pad + F ·
    C = T_flujo + 11·pad + 2·ic + F − vc · D = 13·ic + F − vc · E = g + pad + F − vc."""
    t_flow = sum(titles[menu] for menu in flow)
    t_all = t_flow + titles[tools] + titles[help_]
    n = float(len(flow))
    return {
        "A": ((n + 2, 1.0, 0.0, 0.0, n + 1), t_all),
        "B": ((n + 2, 1.0, 0.0, 0.0, 0.0), t_all),
        "C": ((n, 1.0, 2.0, -1.0, 0.0), t_flow),
        "D": ((0.0, 1.0, n + 2, -1.0, 0.0), 0.0),
        "E": ((1.0, 1.0, 0.0, -1.0, 0.0), titles[geoblender]),
    }[level]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gauss-Jordan con pivote parcial; ``None`` si el sistema es singular."""
    size = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-9:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(size):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][size] / rows[i][i] for i in range(size)]


def fit_topbar_constants(samples: Sequence[Sample],
                         titles: Mapping[str, Mapping[str, float]], *, flow: Sequence[str],
                         tools: str, help_: str, geoblender: str) -> dict[str, float]:
    """Las constantes del modelo a escala 1,0 que mejor reproducen (mínimos cuadrados)
    todas las anchuras medidas de todas las muestras, divididas por su escala efectiva.
    Una muestra puede no tener todos los niveles (los recortados no se miden; T42), y
    ``title_icon`` solo sale si hay alguna medida del nivel A. ``titles``: anchos ``blf``
    a escala 1,0 por idioma y por clase de menú; ``flow``: los 11 menús del flujo. Si las
    medidas no bastan para fijar las demás constantes, vacío."""
    equations: list[tuple[tuple[float, ...], float]] = []
    for sample in samples:
        for level in LEVELS:
            if level not in sample.widths:
                continue
            coefficients, known = _equation(level, titles[sample.language], flow=flow,
                                            tools=tools, help_=help_, geoblender=geoblender)
            equations.append((coefficients, sample.widths[level] / sample.scale - known))
    with_a = any(eq[0][-1] for eq in equations)
    unknowns = [i for i, name in enumerate(UNKNOWNS) if name != "title_icon" or with_a]
    if len({eq[0] for eq in equations}) < len(unknowns):
        return {}
    normal = [[sum(eq[0][i] * eq[0][j] for eq in equations) for j in unknowns]
              for i in unknowns]
    rhs = [sum(eq[0][i] * eq[1] for eq in equations) for i in unknowns]
    solution = _solve(normal, rhs)
    if solution is None:
        return {}
    return {UNKNOWNS[i]: value for i, value in zip(unknowns, solution, strict=True)}


def right_block_px(measures: Sequence[tuple[float, float, float]]) -> float:
    """El bloque derecho de Blender a escala 1,0: el mayor ``(ancho de la región − inicio
    del bloque) / escala`` de las medidas ``(ancho, inicio, escala)``."""
    return max(((width - start) / scale for width, start, scale in measures), default=0.0)


def right_region_px(measures: Sequence[tuple[float, float]]) -> float:
    """La región derecha de la barra (el bloque derecho de Blender 5.2) a escala 1,0: el
    mayor ``ancho / escala efectiva`` de las medidas ``(ancho de la región, escala)``. Es
    la constante ``right_block`` (redondeada hacia arriba, sin margen: es justo lo que
    pierde la región de ``draw_left``)."""
    return max((region / scale for region, scale in measures), default=0.0)


def suggested_right_block(measured_px: float) -> float:
    """La constante ``right_block`` del modelo: lo medido, redondeado hacia arriba, más el
    margen de BS §2.3."""
    return float(math.ceil(measured_px) + RIGHT_BLOCK_MARGIN_PX)


def redraw_ms(seconds: float, iterations: int) -> float:
    """Milisegundos por redibujo."""
    return 1000.0 * seconds / iterations if iterations else 0.0


def best_level(free: Mapping[str, float], clipped: Collection[str], *,
               margin_px: float) -> str | None:
    """El nivel más informativo que cabe según lo medido (RF-003-10): el primero de A a E
    que no está recortado y deja al menos ``margin_px`` libres (el margen del modelo por
    la escala efectiva); ``None`` si ninguno."""
    for level in LEVELS:
        if level in free and level not in clipped and free[level] >= margin_px:
            return level
    return None


def checks(free: Mapping[tuple[str, float, str], float], *,
           chosen: Mapping[tuple[str, float], str] | None = None,
           best: Mapping[tuple[str, float], str | None] | None = None,
           geoblender_ms: float | None, blender_ms: float | None) -> dict[str, bool]:
    """RNF-003-01 con lo medido (``free[(idioma, escala efectiva, nivel)]`` en px reales a
    1920 px), el nivel que eligió el automático (``chosen[(idioma, escala efectiva)]``):
    el de BS §3 (B en español y A o B en inglés a 1,0; C a 1,25) y el más informativo que
    cabe (``best``, de :func:`best_level`), y RNF-003-03 con el redibujo; una medida que
    falta, falsa."""
    chosen = chosen or {}
    best = best or {}
    result: dict[str, bool] = {}
    for language in ("es", "en"):
        b = free.get((language, 1.0, "B"))
        c = free.get((language, 1.25, "C"))
        result[f"RNF-003-01 B {language} 1.0 >= 150"] = b is not None and b >= FREE_B_MIN_PX
        result[f"RNF-003-01 C {language} 1.25 >= 24"] = c is not None and c >= FREE_C_MIN_PX
    result["BS §3 automático es 1.0 = B"] = chosen.get(("es", 1.0)) == "B"
    result["BS §3 automático en 1.0 = A o B"] = chosen.get(("en", 1.0)) in ("A", "B")
    for language in ("es", "en"):
        result[f"BS §3 automático {language} 1.25 = C"] = chosen.get((language, 1.25)) == "C"
    for (language, scale), level in sorted(chosen.items()):
        expected = best.get((language, scale))
        result[f"RF-003-10 automático {language} {scale:g} = el más informativo que cabe"] = (
            expected is not None and level == expected)
    result["RNF-003-03 redibujo <= Blender + 1 ms"] = (
        geoblender_ms is not None and blender_ms is not None
        and geoblender_ms <= blender_ms + REDRAW_MARGIN_MS
    )
    return result
