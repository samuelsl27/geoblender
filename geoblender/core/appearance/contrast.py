# SPDX-License-Identifier: GPL-3.0-or-later
"""Contraste y daltonismo de los colores propios (spec 019, T28; RF-019-22; UI-30, UI-31).

La fórmula de contraste de WCAG 2.2 (luminancia relativa, ``(L1 + 0,05) / (L2 + 0,05)``) y una simulación de tres
daltonismos (Machado, Oliveira y Fernandes, 2009, severidad completa, sobre RGB lineal) con la distancia CIE76 en
Lab, para comprobar que la paleta de Okabe e Ito se sigue distinguiendo. Dominio puro, sin dependencias.
Los colores van en ``#RRGGBB``.
"""

from __future__ import annotations

__all__ = ["GRAPHIC_MIN", "MIN_CVD_DISTANCE", "TEXT_MIN", "THEME_BACKGROUNDS", "contrast_ratio", "lab_distance",
           "passes", "relative_luminance", "simulate"]

TEXT_MIN = 4.5
"""El contraste mínimo de un texto (UI-30)."""
GRAPHIC_MIN = 3.0
"""El contraste mínimo de un color que se pinta, un icono o un borde (UI-30)."""
MIN_CVD_DISTANCE = 12.0
"""La distancia CIE76 mínima entre dos colores de la paleta tras simular un daltonismo."""

THEME_BACKGROUNDS: dict[str, str] = {"dark": "#3D3D3D", "light": "#646464"}
"""El fondo de la vista 3D de cada tema incluido de Blender 5.2: el oscuro es el del tema por defecto y el claro el de
``Blender_Light.xml`` (``ThemeView3D``, degradado)."""

_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}


def _rgb(color: str) -> tuple[float, float, float]:
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
        raise ValueError(f"color no válido: {color!r} (se espera #RRGGBB)")
    try:
        return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]
    except ValueError:
        raise ValueError(f"color no válido: {color!r} (se espera #RRGGBB)") from None


def _linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _encode(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def relative_luminance(color: str) -> float:
    """La luminancia relativa de WCAG de ``color``."""
    r, g, b = (_linear(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    """El contraste de WCAG entre dos colores (de 1 a 21; simétrico)."""
    a, b = relative_luminance(first), relative_luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def passes(color: str, background: str, minimum: float) -> bool:
    """Si ``color`` sobre ``background`` llega al contraste ``minimum``."""
    return contrast_ratio(color, background) >= minimum


def simulate(color: str, kind: str) -> tuple[float, float, float]:
    """Lab de ``color`` visto con el daltonismo ``kind`` (``protanopia``, ``deuteranopia`` o ``tritanopia``)."""
    matrix = _MATRICES[kind]
    lin = [_linear(c) for c in _rgb(color)]
    seen = [sum(row[i] * lin[i] for i in range(3)) for row in matrix]
    return _lab(*(_linear(_encode(v)) for v in seen))


def _lab(r: float, g: float, b: float) -> tuple[float, float, float]:
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_distance(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    """La distancia CIE76 entre dos colores en Lab."""
    return sum((a - b) ** 2 for a, b in zip(first, second)) ** 0.5
