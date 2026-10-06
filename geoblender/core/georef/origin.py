# SPDX-License-Identifier: GPL-3.0-or-later
"""Ventana de trabajo, unidad de alineación y GeoOrigin (spec 002; RF-002-24;
ADR-0005, ADR-0014).

Todas las coordenadas de este módulo son **absolutas** (CRS del proyecto, m, float64).

- La ventana tecleada se amplía hacia fuera (:func:`align_window`) a múltiplos de la
  **unidad de alineación** del paso de rejilla (:func:`alignment_unit`: el menor entero de
  metros múltiplo del paso), para que coincida celda a celda con la rejilla del proyecto de
  la spec 006 (que importa ``alignment_unit`` de aquí y no la redefine).
- El GeoOrigin (:func:`choose_origin`) es el centro de la ventana **ya ampliada**
  redondeado a 100 m por eje con los empates hacia arriba, ``100 · floor(c / 100 + 0,5)``:
  determinista, y no el redondeo al par de ``round()`` (700 250 → 700 300, no 700 200).
  Z0 es 0 o el entero que indique el usuario.

El GeoOrigin son tres enteros (metros), X0 e Y0 múltiplos de 100 y Z0 entre −10 000 y
10 000: en la escena de Blender se guardan como ``IntProperty`` (32 bits con signo), así que
también se comprueba que quepan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..errors import ValidationError

ORIGIN_STEP_M = 100  # X0 e Y0, múltiplos de 100 m (ADR-0005)
Z0_MIN_M = -10_000
Z0_MAX_M = 10_000
INT_PROPERTY_MIN = -(2**31)
INT_PROPERTY_MAX = 2**31 - 1
GRID_STEP_MIN_M = 0.5
GRID_STEP_MAX_M = 5.0
DEFAULT_GRID_STEP_M = 1.0

_WINDOW = "Ventana de trabajo"
_ORIGIN = "GeoOrigin"
_STEP_FIELD = "paso de rejilla"


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Window:
    """Rectángulo absoluto (m) de la ventana de trabajo: ``xmin < xmax`` e
    ``ymin < ymax``, números finitos guardados como float64."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def __post_init__(self) -> None:
        for field in ("xmin", "ymin", "xmax", "ymax"):
            value = getattr(self, field)
            if not _is_number(value) or not math.isfinite(value):
                raise ValidationError(
                    "core.window_value_invalid",
                    "cada esquina de la ventana debe ser un número finito, en metros",
                    obj=_WINDOW,
                    field=field,
                    value=value,
                )
            object.__setattr__(self, field, float(value))
        for low, high in (("xmin", "xmax"), ("ymin", "ymax")):
            if getattr(self, low) >= getattr(self, high):
                raise ValidationError(
                    "core.window_inverted",
                    f"{low} debe ser menor que {high} (la ventana está vacía o tiene los "
                    "ejes invertidos)",
                    obj=_WINDOW,
                    field=f"{low}–{high}",
                    value=(getattr(self, low), getattr(self, high)),
                    shown=f"{getattr(self, low)!r}–{getattr(self, high)!r}".replace(
                        ".", ","
                    ),
                )

    @property
    def width(self) -> float:
        """Ancho en X (m)."""
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        """Alto en Y (m)."""
        return self.ymax - self.ymin

    @property
    def centre(self) -> tuple[float, float]:
        """Centro (x, y), absoluto (m), en float64."""
        return ((self.xmin + self.xmax) / 2.0, (self.ymin + self.ymax) / 2.0)


def _check_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(
            "core.origin_not_integer",
            "el GeoOrigin son metros enteros (sin decimales)",
            obj=_ORIGIN,
            field=field,
            value=value,
        )
    if not INT_PROPERTY_MIN <= value <= INT_PROPERTY_MAX:
        raise ValidationError(
            "core.origin_out_of_range",
            f"no cabe en un entero de 32 bits (de {INT_PROPERTY_MIN} a "
            f"{INT_PROPERTY_MAX}), que es como lo guarda la escena de Blender",
            obj=_ORIGIN,
            field=field,
            value=value,
        )
    return value


@dataclass(frozen=True)
class GeoOrigin:
    """Origen local del proyecto en metros enteros: X0 e Y0 múltiplos de 100 y Z0 entre
    −10 000 y 10 000 (por defecto 0)."""

    x0: int
    y0: int
    z0: int = 0

    def __post_init__(self) -> None:
        for field, label in (("x0", "X0"), ("y0", "Y0")):
            value = _check_int(getattr(self, field), label)
            if value % ORIGIN_STEP_M != 0:
                raise ValidationError(
                    "core.origin_not_multiple",
                    f"debe ser múltiplo de {ORIGIN_STEP_M} m (ADR-0005)",
                    obj=_ORIGIN,
                    field=label,
                    value=value,
                )
        z0 = _check_int(self.z0, "Z0")
        if not Z0_MIN_M <= z0 <= Z0_MAX_M:
            raise ValidationError(
                "core.origin_z0_out_of_range",
                f"debe estar entre {Z0_MIN_M} y {Z0_MAX_M} m",
                obj=_ORIGIN,
                field="Z0",
                value=z0,
            )

    def as_tuple(self) -> tuple[int, int, int]:
        """(X0, Y0, Z0)."""
        return (self.x0, self.y0, self.z0)


def check_grid_step(grid_step_m: object) -> float:
    """El paso de rejilla como float si es válido (de 0,5 a 5 m, múltiplo de 0,5);
    :class:`ValidationError` si no."""
    step = float(grid_step_m) if _is_number(grid_step_m) else math.nan  # type: ignore[arg-type]
    in_range = math.isfinite(step) and GRID_STEP_MIN_M <= step <= GRID_STEP_MAX_M
    if not in_range or not (step * 2).is_integer():
        raise ValidationError(
            "core.grid_step_invalid",
            "debe estar entre 0,5 y 5 m y ser múltiplo de 0,5 m (ADR-0014)",
            obj="Proyecto",
            field=_STEP_FIELD,
            value=grid_step_m,
        )
    return step


def alignment_unit(grid_step_m: float) -> int:
    """El menor número entero de metros múltiplo del paso: 0,5 y 1 → 1; 1,5 → 3; 2 → 2;
    2,5 → 5; 4,5 → 9; 5 → 5. :class:`ValidationError` si el paso no es válido."""
    halves = round(check_grid_step(grid_step_m) * 2)  # paso = halves / 2, exacto
    return halves // math.gcd(halves, 2)


def align_window(window: Window, grid_step_m: float) -> Window:
    """La ventana ampliada hacia fuera a múltiplos de :func:`alignment_unit` (``floor``
    de los mínimos y ``ceil`` de los máximos); absoluta (m)."""
    unit = alignment_unit(grid_step_m)
    return Window(
        float(math.floor(window.xmin / unit) * unit),
        float(math.floor(window.ymin / unit) * unit),
        float(math.ceil(window.xmax / unit) * unit),
        float(math.ceil(window.ymax / unit) * unit),
    )


def _round_hundred(value: float) -> int:
    """Múltiplo de 100 más cercano, con los empates hacia arriba."""
    return ORIGIN_STEP_M * math.floor(value / ORIGIN_STEP_M + 0.5)


def choose_origin(window: Window, z0: int = 0) -> GeoOrigin:
    """GeoOrigin del centro de ``window``, que debe ser la ventana **ya alineada**
    (:func:`align_window`): X0 e Y0 redondeados a 100 m con los empates hacia arriba, y
    ``z0`` (0 por defecto)."""
    cx, cy = window.centre
    return GeoOrigin(_round_hundred(cx), _round_hundred(cy), z0)
