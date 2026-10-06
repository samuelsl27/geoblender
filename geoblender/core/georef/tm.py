# SPDX-License-Identifier: GPL-3.0-or-later
"""Proyección transversa de Mercator de Krüger (spec 002, D-12; RF-002-03; plan 002 §5.4,
«Ámbito del CRS y huso extendido»).

Solo sirve para decidir si una ventana de trabajo cae en el ámbito de su CRS o en su
**huso extendido** y para calcular la deformación de escala que se avisa: no reproyecta
datos (las transformaciones entre CRS llegan con la spec 006, D-1). Python puro, en
float64.

Coordenadas: ``x``, ``y`` son **absolutas** en el CRS proyectado (m); ``lon``, ``lat``,
geográficas en grados de su CRS geográfico base (el mismo elipsoide, sin cambio de datum).

Algoritmo: series de Krüger hasta el orden 6 en el tercer aplanamiento ``n`` (Karney, C.
F. F. 2011, «Transverse Mercator with an accuracy of a few nanometers», *Journal of
Geodesy* 85, 475–485, ecuaciones 7–25 y 35–36), la forma que usa PROJ (``etmerc``) para
la proyección UTM. La latitud de la inversa se obtiene de la latitud conforme por Newton
(ecuaciones 19–21). Dentro de ±6° del meridiano central (el huso extendido) el error es
de nanómetros; la referencia contra PROJ está en ``tests/referencia/core``.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass

ORDER = 6
_NEWTON_ITERATIONS = 10
_NEWTON_TOLERANCE = 1e-15


@dataclass(frozen=True)
class TransverseMercator:
    """Parámetros de una proyección transversa de Mercator: semieje mayor ``a`` (m),
    inverso del aplanamiento ``inv_f``, meridiano central ``lon0`` (grados), factor de
    escala en él ``k0`` y falsos este y norte ``fe``, ``fn`` (m)."""

    a: float
    inv_f: float
    lon0: float
    k0: float
    fe: float
    fn: float

    def __post_init__(self) -> None:
        values = (self.a, self.inv_f, self.lon0, self.k0, self.fe, self.fn)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"parámetros de la transversa de Mercator no finitos: {values}")
        if self.a <= 0 or self.inv_f <= 1 or self.k0 <= 0:
            raise ValueError(
                "la transversa de Mercator necesita a > 0, 1/f > 1 y k0 > 0 "
                f"(a = {self.a}, 1/f = {self.inv_f}, k0 = {self.k0})"
            )


@dataclass(frozen=True)
class _Series:
    """Constantes del elipsoide para las series de Krüger."""

    n: float
    e: float  # primera excentricidad
    rectifying: float  # A, radio de la esfera rectificante (m)
    alpha: tuple[float, ...]  # directa, α1…α6
    beta: tuple[float, ...]  # inversa, β1…β6


@functools.cache
def _series(inv_f: float) -> _Series:
    f = 1.0 / inv_f
    n = f / (2.0 - f)
    n2, n3, n4, n5, n6 = n**2, n**3, n**4, n**5, n**6
    alpha = (
        n / 2 - 2 * n2 / 3 + 5 * n3 / 16 + 41 * n4 / 180 - 127 * n5 / 288 + 7891 * n6 / 37800,
        13 * n2 / 48 - 3 * n3 / 5 + 557 * n4 / 1440 + 281 * n5 / 630
        - 1983433 * n6 / 1935360,
        61 * n3 / 240 - 103 * n4 / 140 + 15061 * n5 / 26880 + 167603 * n6 / 181440,
        49561 * n4 / 161280 - 179 * n5 / 168 + 6601661 * n6 / 7257600,
        34729 * n5 / 80640 - 3418889 * n6 / 1995840,
        212378941 * n6 / 319334400,
    )
    beta = (
        n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360 - 81 * n5 / 512 + 96199 * n6 / 604800,
        n2 / 48 + n3 / 15 - 437 * n4 / 1440 + 46 * n5 / 105 - 1118711 * n6 / 3870720,
        17 * n3 / 480 - 37 * n4 / 840 - 209 * n5 / 4480 + 5569 * n6 / 90720,
        4397 * n4 / 161280 - 11 * n5 / 504 - 830251 * n6 / 7257600,
        4583 * n5 / 161280 - 108847 * n6 / 3991680,
        20648693 * n6 / 638668800,
    )
    # A / a, sin el semieje (cada proyección pone el suyo).
    rectifying = (1 + n2 / 4 + n4 / 64 + n6 / 256) / (1 + n)
    return _Series(n, math.sqrt(f * (2.0 - f)), rectifying, alpha, beta)


def _conformal_tan(tau: float, e: float) -> float:
    """τ' = tan de la latitud conforme, desde τ = tan φ (Karney, ec. 7–9)."""
    sigma = math.sinh(e * math.atanh(e * tau / math.hypot(1.0, tau)))
    return tau * math.hypot(1.0, sigma) - sigma * math.hypot(1.0, tau)


def _geographic_tan(tau_prime: float, e: float) -> float:
    """τ = tan φ desde τ' por Newton (Karney, ec. 19–21)."""
    e2 = e * e
    tau = tau_prime
    for _ in range(_NEWTON_ITERATIONS):
        current = _conformal_tan(tau, e)
        step = (
            (tau_prime - current)
            / math.hypot(1.0, current)
            * (1 + (1 - e2) * tau * tau)
            / ((1 - e2) * math.hypot(1.0, tau))
        )
        tau += step
        if abs(step) <= _NEWTON_TOLERANCE * max(1.0, abs(tau)):
            break
    return tau


def _conformal(lon: float, lat: float, tm: TransverseMercator) -> tuple[float, float, float, float]:
    """(ξ', η', τ', λ) del punto: coordenadas de la esfera conforme (Karney, ec. 10–11)."""
    series = _series(tm.inv_f)
    lam = math.radians(lon - tm.lon0)
    tau_prime = _conformal_tan(math.tan(math.radians(lat)), series.e)
    xi = math.atan2(tau_prime, math.cos(lam))
    eta = math.asinh(math.sin(lam) / math.hypot(tau_prime, math.cos(lam)))
    return xi, eta, tau_prime, lam


def tm_forward(lon: float, lat: float, tm: TransverseMercator) -> tuple[float, float]:
    """(x, y) absolutas (m) del punto geográfico (``lon``, ``lat``, grados)."""
    series = _series(tm.inv_f)
    xi_p, eta_p, _tau_p, _lam = _conformal(lon, lat, tm)
    xi, eta = xi_p, eta_p
    for j, alpha in enumerate(series.alpha, start=1):
        xi += alpha * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += alpha * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    scale = tm.k0 * tm.a * series.rectifying
    return tm.fe + scale * eta, tm.fn + scale * xi


def tm_inverse(x: float, y: float, tm: TransverseMercator) -> tuple[float, float]:
    """(lon, lat) en grados del punto absoluto (``x``, ``y``, m).

    :class:`ValueError` si el punto está tan lejos del meridiano central que no se puede
    calcular (más de un cuarto de vuelta: no es de este CRS)."""
    series = _series(tm.inv_f)
    scale = tm.k0 * tm.a * series.rectifying
    xi = (y - tm.fn) / scale
    eta = (x - tm.fe) / scale
    if not (math.isfinite(xi) and math.isfinite(eta)) or abs(eta) > math.pi:
        raise ValueError(f"punto fuera del alcance de la proyección: ({x}, {y})")
    xi_p, eta_p = xi, eta
    for j, beta in enumerate(series.beta, start=1):
        xi_p -= beta * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta_p -= beta * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
    tau_prime = math.sin(xi_p) / math.hypot(math.sinh(eta_p), math.cos(xi_p))
    lam = math.atan2(math.sinh(eta_p), math.cos(xi_p))
    tau = _geographic_tan(tau_prime, series.e)
    return tm.lon0 + math.degrees(lam), math.degrees(math.atan(tau))


def tm_scale(lon: float, lat: float, tm: TransverseMercator) -> float:
    """Factor de escala ``k`` de la proyección en el punto (``lon``, ``lat``, grados):
    1 + k·10⁻⁶ son los ppm que se deforma una distancia (Karney, ec. 25)."""
    series = _series(tm.inv_f)
    xi_p, eta_p, tau_p, lam = _conformal(lon, lat, tm)
    p_prime, q_prime = 1.0, 0.0
    for j, alpha in enumerate(series.alpha, start=1):
        p_prime += 2 * j * alpha * math.cos(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        q_prime += 2 * j * alpha * math.sin(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    ratio = (1 - series.n) / (1 + series.n)  # b / a
    tan_phi = math.tan(math.radians(lat))
    return (
        tm.k0
        * series.rectifying
        * math.hypot(1.0, ratio * tan_phi)
        * math.hypot(p_prime, q_prime)
        / math.hypot(tau_p, math.cos(lam))
    )
