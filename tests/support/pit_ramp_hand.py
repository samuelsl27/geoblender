# SPDX-License-Identifier: GPL-3.0-or-later
"""El oráculo a mano de las rampas de la corta (spec 018, T14; HU-018-3; RF-018-16, 17, 21; CE-018-05 y 06; plan 018 §5.4 A8 y A9).

**Independiente del producto** (no importa nada de ``geoblender``): aritmética exacta con :class:`~fractions.Fraction` en todo lo
racional (la pendiente, la altura de banco, el ancho de la sección, las cotas, las abscisas) y con :class:`~decimal.Decimal` de 70
cifras donde entra ``tan α`` (``1/√3`` con α = 60°). Dice, sin código de producto, cuánto sube cada tramo, a qué cota y abscisa está
cada estación, cuánto se retranquea la cresta (``W + (z_{k+1} − z(s))/tan α``: DIFF-018-2) y cuánto mide la pared sobre la rampa
(entre ``h`` y ``0``).

Lectura de la spec 0.4 (DIFF-018b): ``s`` se mide **por banco** (sobre el eje, en el sentido pedido); el tramo ``k + 1`` empieza en el
punto del pie ``k + 1`` más cercano al fin del tramo ``k``; los dos ejes se unen con un **enlace horizontal recto** de ``W + B`` m a
``z_{k+1}`` (:func:`link_length`) que cuenta en el eje y no en la rampa (125 m de rampa por banco; eje de 5 bancos 695 m). La vieja
lectura literal ``s_{k+1} = s_k + L_k`` ya no está: con pies de radios distintos dejaba el fin y el inicio en azimuts distintos (G-4).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any

PRECISION = 70
"""Cifras decimales del cálculo con ``tan α`` (como el oráculo de la T04)."""

# --- Los datos de CE-018-05 y 06 (valores de prueba de la spec y del perfil de pista de referencia de ``road_data``) -----------
HEIGHT_M = Fraction(10)
"""Altura de banco de ``EXPL_10_60_6`` (m)."""
FACE_DEG = 60
"""Ángulo de cara de ``EXPL_10_60_6`` (°)."""
BERM_M = Fraction(6)
"""Berma de ``EXPL_10_60_6`` (m)."""
SECTION_M = Fraction(23, 2)
"""Anchura de la sección del perfil de pista de referencia: calzada ``3 × 3,5`` más caballón ``1`` (11,5 m)."""
SPIRAL_GRADIENT = Fraction(8, 100)
ZIGZAG_GRADIENT = Fraction(10, 100)
"""Las pendientes de CE-018-05 (8 %) y CE-018-06 (10 %) como fracción (0,08 y 0,10 exactos)."""
FLOOR_RADIUS_M = Fraction(50)
FLOOR_Z_M = Fraction(125)
BENCHES = 5
"""La corta circular de CE-018-03: fondo de 50 m de radio a 125 m y cinco bancos."""
STATIONS = 8
"""Estaciones de la figura en cifras (de ``s_k`` a ``s_k + L_k``, a pasos iguales)."""


def run_length(height_m: Fraction = HEIGHT_M, gradient: Fraction = SPIRAL_GRADIENT) -> Fraction:
    """La longitud de eje que pide subir un banco: ``h / g`` (125 m con g = 8 %; 100 m con g = 10 %)."""
    return Fraction(height_m) / Fraction(gradient)


def anchors(count: int = BENCHES, z0_m: Fraction = FLOOR_Z_M, height_m: Fraction = HEIGHT_M) -> tuple[Fraction, ...]:
    """Las cotas de ancla ``z_0 … z_count``: el pie del banco ``k`` está a ``z_k`` y su cresta a ``z_{k+1}`` (``z0 + k·h``)."""
    return tuple(Fraction(z0_m) + k * Fraction(height_m) for k in range(count + 1))


def cot_alpha(face_deg: int = FACE_DEG) -> Decimal:
    """``1 / tan α`` en 70 cifras (``1/√3`` con 60°; para 45° es 1 exacto)."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        if face_deg == 60:
            return Decimal(1) / Decimal(3).sqrt()
        if face_deg == 45:
            return Decimal(1)
        raise ValueError(f"cot α a mano solo para 45° y 60°, no {face_deg}°")


def dec(value: Fraction) -> Decimal:
    """Un ``Fraction`` como ``Decimal`` de 70 cifras (para mezclarlo con ``cot α``)."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return Decimal(value.numerator) / Decimal(value.denominator)


def setback(face_height_m: Fraction, width_m: Fraction = SECTION_M, face_deg: int = FACE_DEG) -> Decimal:
    """El retranqueo de la cresta sobre el pie nominal: ``W + (z_{k+1} − z(s))/tan α``, con ``face_height = z_{k+1} − z(s)``
    (DIFF-018-2). Vale ``W + h/tan α`` al empezar el tramo y ``W`` al acabar."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return dec(Fraction(width_m)) + dec(Fraction(face_height_m)) * cot_alpha(face_deg)


@dataclass(frozen=True)
class Station:
    """Una estación del eje de un tramo: banco ``k``, abscisa relativa y absoluta, cota, pendiente, pared y retranqueo."""

    bench: int
    s_rel_m: Fraction
    s_abs_m: Fraction
    z_m: Fraction
    face_height_m: Fraction
    setback_m: Decimal


def tramo_stations(bench: int, *, count: int = STATIONS, gradient: Fraction = SPIRAL_GRADIENT, height_m: Fraction = HEIGHT_M,
                   width_m: Fraction = SECTION_M, face_deg: int = FACE_DEG, z0_m: Fraction = FLOOR_Z_M,
                   s_start_m: Fraction | None = None) -> tuple[Station, ...]:
    """Las ``count`` estaciones (a pasos iguales, extremos incluidos) del tramo del banco ``bench`` con transición nula.

    ``s_start_m`` es la abscisa de inicio del tramo **sobre su banco** (por defecto 0: ``s`` se mide por banco, DIFF-018b)."""
    run = run_length(height_m, gradient)
    z_k = Fraction(z0_m) + bench * Fraction(height_m)
    s_k = Fraction(0) if s_start_m is None else Fraction(s_start_m)
    found = []
    for i in range(count):
        s_rel = run * Fraction(i, count - 1)
        z = z_k + Fraction(gradient) * s_rel
        face = z_k + Fraction(height_m) - z
        found.append(Station(bench, s_rel, s_k + s_rel, z, face, setback(face, width_m, face_deg)))
    return tuple(found)


def link_length(width_m: Fraction = SECTION_M, berm_m: Fraction = BERM_M) -> Fraction:
    """La longitud del **enlace horizontal** (propuesta del DIFF-018b) entre el fin del tramo ``k`` y el inicio del ``k + 1``: el
    pie del banco ``k + 1`` es la cresta ``k`` retranqueada más la berma (``f_k + W + B``) y el eje de cada tramo va a ``W/2`` de
    su pie, de modo que los dos ejes distan ``W + B`` (11,5 + 6 = 17,5 m), a la cota ``z_{k+1}``, sin depender de ``α``."""
    return Fraction(width_m) + Fraction(berm_m)


@dataclass(frozen=True)
class SpiralTotals:
    """Los totales de la espiral de ``count`` bancos con transición nula."""

    ramp_per_bench_m: Fraction
    ramp_m: Fraction
    links: int
    links_m: Fraction
    axis_m: Fraction
    rise_m: Fraction
    ramp_gradient: Fraction
    mean_gradient: Fraction


def spiral_totals(count: int = BENCHES, gradient: Fraction = SPIRAL_GRADIENT, height_m: Fraction = HEIGHT_M,
                  width_m: Fraction = SECTION_M, berm_m: Fraction = BERM_M) -> SpiralTotals:
    """CE-018-05: 125 m de rampa por banco a 8,000 %; con la propuesta del enlace, ``count − 1`` enlaces horizontales de 17,5 m."""
    per_bench = run_length(height_m, gradient)
    ramp = count * per_bench
    links = count - 1
    links_m = links * link_length(width_m, berm_m)
    rise = count * Fraction(height_m)
    return SpiralTotals(per_bench, ramp, links, links_m, ramp + links_m, rise, rise / ramp, rise / (ramp + links_m))


def foot_radii(count: int = BENCHES, *, base_m: Fraction = FLOOR_RADIUS_M, face_deg: int = FACE_DEG, height_m: Fraction = HEIGHT_M,
               berm_m: Fraction = BERM_M) -> tuple[Decimal, ...]:
    """Los radios de pie nominales ``f_k`` de la corta circular (sin retranqueo): ``f_{k+1} = f_k + h/tan α + B`` (CE-018-03)."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        step = dec(Fraction(height_m)) * cot_alpha(face_deg) + dec(Fraction(berm_m))
        return tuple(dec(Fraction(base_m)) + k * step for k in range(count))


def first_tramo_sweep_deg(*, base_m: Fraction = FLOOR_RADIUS_M, width_m: Fraction = SECTION_M, height_m: Fraction = HEIGHT_M,
                          gradient: Fraction = SPIRAL_GRADIENT) -> Decimal:
    """El ángulo (°) que recorre el tramo del banco 0 de la corta circular: su eje es el círculo de radio ``f_0 + W/2`` (55,75 m) y mide
    ``h/g`` (125 m) de arco. Solo el banco 0 es circular: los pies siguientes llevan el bulto de la rampa anterior."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        radius = dec(Fraction(base_m) + Fraction(width_m) / 2)
        pi = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899")
        return dec(run_length(height_m, gradient)) / radius * 180 / pi


# --- El zig-zag (CE-018-06) -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ZigzagTotals:
    """Los totales a mano de un zig-zag de ``benches`` bancos."""

    benches: int
    tramo_m: Fraction
    returns: int
    platform_m: Fraction
    ramp_m: Fraction
    platforms_m: Fraction
    axis_m: Fraction
    rise_m: Fraction


def zigzag_totals(benches: int, platform_m: Fraction, gradient: Fraction = ZIGZAG_GRADIENT, height_m: Fraction = HEIGHT_M
                  ) -> ZigzagTotals:
    """Un tramo recto de ``h/g`` por banco, ``benches − 1`` retornos y una plataforma horizontal de ``platform_m`` de eje en cada uno:
    longitud ``N·h/g + (N − 1)·P`` y desnivel ``N·h``. ``platform_m`` es la longitud **de eje** de la plataforma (recta más curva de
    giro): la spec solo dice «no menor que la mínima» y la propuesta es ``max(min_platform, π·Rgiro)`` (DIFF-018b)."""
    if benches < 1:
        raise ValueError("al menos un banco")
    tramo = run_length(height_m, gradient)
    returns = benches - 1
    return ZigzagTotals(benches, tramo, returns, Fraction(platform_m), benches * tramo, returns * Fraction(platform_m),
                        benches * tramo + returns * Fraction(platform_m), benches * Fraction(height_m))


def zigzag_fit(side_m: Fraction, platform_m: Fraction, gradient: Fraction = ZIGZAG_GRADIENT, height_m: Fraction = HEIGHT_M
               ) -> tuple[Fraction, Fraction, bool]:
    """``(necesaria, disponible, cabe)`` sobre un lado recto de ``side_m`` m: el tramo más su plataforma, ``h/g + P`` (propuesta del
    DIFF-018b para RF-018-20: 100 + 41,5 = 141,5 m con ``P = 2·Rgiro + W``; sobre el lado de 200 m de CE-018-06 cabe y sobre uno de
    120 m no)."""
    needed = run_length(height_m, gradient) + Fraction(platform_m)
    return needed, Fraction(side_m), needed <= Fraction(side_m)


def face_gradient(face_height_m: Fraction, setback_m: Decimal, width_m: Fraction = SECTION_M) -> Any:
    """``tan`` de la inclinación de la cara sobre la rampa: ``altura / (retranqueo − W)`` (``tan α`` en todas las estaciones con
    pared; ``None`` si la pared mide 0)."""
    run = setback_m - dec(Fraction(width_m))
    return None if face_height_m == 0 else dec(Fraction(face_height_m)) / run
