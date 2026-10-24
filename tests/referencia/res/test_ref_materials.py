# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-011-02 y CE-011-03: regresión de los errores 18, 63 y 67 del proyecto de referencia con la
columna sintética (spec 011, T09 y T10; HU-011-3; RF-011-12, RF-011-13, RF-011-14, RF-011-15,
RF-011-16; plan 011 A7, A8, §7.1, D-7, D-10 y D-23; constitución, principio 2).

Los errores 18 y 63: el volumen de un escombro se **descontaba en proporción** de las demás
unidades, así que la cifra de material útil dependía de cómo se copió un script. En la 011 una
unidad antrópica tiene su volumen **desde su base hacia arriba** y las de debajo quedan
**cortadas en esa base** (en su sitio, RF-011-14).

La columna (``tests/support/res_fixtures.py``, 50 × 40 celdas de 2 m, planos inclinados y huellas
alineadas con las celdas, así que la suma en los centros de celda es la integral): un acopio
de 4 m sobre el terreno (3.600 m³), un escombro de 5 m sobre la capa útil (2.000 m³), la montera
(58.570 m³), la capa útil compuesta (107.940 m³) y el muro (64.410 m³); desmonte 236.520 m³ y un
terraplén de 600 m³ que no se reparte. Sin la unidad de escombro, con las mismas superficies, la
capa útil **no cambia** y la montera recibe los 2.000 m³ del escombro (60.570 m³). Umbral de
presencia de lo antrópico, 0,30 m (D-7). Tolerancia: 10⁻⁹ relativo (D-14 b; las cifras
analíticas de la columna salen de fórmulas en float64).

El error 67: un acopio se pesaba con la densidad **in situ**, K veces más de lo que pesa. En la
011 lo suelto pesa V·ρ/K (RF-011-16): el acopio de la columna (3.600 m³, ρ 2,60 t/m³ y K 1,50,
valores sintéticos de prueba) pesa 6.240 t, no 9.360 t.
"""

from __future__ import annotations

import dataclasses
import unittest

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

kernel = import_geoblender("reserves.kernel")
tonnage = import_geoblender("reserves.tonnage")
res_params = import_geoblender("reserves.params")
materials = import_geoblender("reserves.materials")

TOLERANCE = 1e-9
"""Error relativo admitido frente a las cifras analíticas y en el cierre (D-14 b)."""
CUT_AREA_M2 = 80.0 * 100.0 - 10.0 * 20.0
"""El área de desmonte de la columna: la ventana sin el terraplén (m²)."""


def _cubicate(case, *, band: int | None = None):
    """El núcleo con unidades sobre la columna ``case`` (e = 0; umbral de presencia 0,30 m), de
    una vez o por bandas de ``band`` filas."""
    grid = case.grid
    accumulators = kernel.Accumulators(grid, units=len(case.units),
                                       presence_m=fx.ANTHROPIC_PRESENCE_M)
    height = grid.nrows if band is None else band
    for first in range(0, grid.nrows, height):
        rows = slice(first, min(first + height, grid.nrows))
        bases, thicknesses = fx.column_layers(case, rows)
        kernel.band_step(accumulators, kernel.BandValues(
            first, case.start.values[rows], case.final.values[rows], bases=bases,
            thicknesses=thicknesses))
    return accumulators.result()


class DebrisInPlaceTest(unittest.TestCase):
    """CE-011-02 (RF-011-12, RF-011-14): el escombro, en su sitio."""

    def _check_units(self, case, result) -> dict[str, float]:
        """Cada unidad, su volumen analítico; las unidades suman el desmonte (el analítico) y el
        terraplén no se reparte. Da el volumen de cada unidad por su código."""
        found = dict(zip((unit.code for unit in case.units),
                         result.unit_volume_m3[kernel.ALL], strict=True))
        for unit in case.units:
            with self.subTest(unit=unit.code):
                self.assertLessEqual(abs(found[unit.code] - unit.expected_m3),
                                     TOLERANCE * unit.expected_m3)
        cut = result.cut_m3[kernel.ALL]
        self.assertLessEqual(abs(cut - case.cut_m3), TOLERANCE * case.cut_m3)
        self.assertLessEqual(abs(sum(found.values()) - cut), TOLERANCE * cut)
        self.assertLessEqual(abs(result.fill_m3[kernel.ALL] - case.fill_m3),
                             TOLERANCE * case.fill_m3)
        self.assertGreater(result.fill_m3[kernel.ALL], 0.0)
        return found

    def test_the_useful_layer_does_not_depend_on_the_debris(self) -> None:
        """CE-011-02: con un escombro de 5 m sobre la capa útil, la capa útil es la analítica
        (107.940 m³) y la misma, **bit a bit**, sin la unidad de escombro; su volumen no se
        descuenta en proporción de las demás: lo pierde solo la montera (58.570 frente a
        60.570 m³). Las unidades suman el desmonte (236.520 m³) ≤ 10⁻⁹; el terraplén (600 m³)
        no se reparte."""
        with_debris = fx.material_column(debris=True)
        without_debris = fx.material_column(debris=False)
        found = self._check_units(with_debris, _cubicate(with_debris))
        alone = self._check_units(without_debris, _cubicate(without_debris))
        self.assertEqual(found["capa_util"], alone["capa_util"])
        self.assertLessEqual(abs(found["capa_util"] - 107_940.0), TOLERANCE * 107_940.0)
        self.assertLessEqual(abs(found["escombro"] - 2_000.0), TOLERANCE * 2_000.0)
        self.assertLessEqual(abs(alone["montera"] - found["montera"] - found["escombro"]),
                             TOLERANCE * alone["montera"])
        for code in ("acopio", "muro"):
            self.assertEqual(found[code], alone[code], code)

    def test_presence_and_areas(self) -> None:
        """RF-011-13 y RF-011-14: el acopio y el escombro solo están donde su espesor pasa del
        umbral (900 y 400 m² de los 7.800 m² de desmonte: ausentes en el resto); ninguna base
        sin dato ni ningún cruce (la base de la montera es la del escombro: espesor 0, no
        cruce). Por bandas de 7 filas, lo mismo (≤ 10⁻⁹)."""
        case = fx.material_column()
        result = _cubicate(case)
        absent = dict(zip((unit.code for unit in case.units), result.unit_absent_m2[kernel.ALL],
                          strict=True))
        self.assertEqual(absent, {"acopio": CUT_AREA_M2 - 900.0,
                                  "escombro": CUT_AREA_M2 - 400.0,
                                  "montera": 0.0, "capa_util": 0.0, "muro": 0.0})
        np.testing.assert_array_equal(result.unit_nodata_m2, 0.0)
        np.testing.assert_array_equal(result.unit_crossed_m2, 0.0)
        by_bands = _cubicate(case, band=7)
        total = result.cut_m3[kernel.ALL]
        worst = float(np.max(np.abs(by_bands.unit_volume_m3 - result.unit_volume_m3)))
        self.assertLessEqual(worst, TOLERANCE * total)
        np.testing.assert_array_equal(by_bands.unit_absent_m2, result.unit_absent_m2)


def _parameters(case) -> dict[str, float]:
    """La densidad in situ, el K y los porcentajes (sintéticos de prueba) de la columna ``case``,
    por sus claves de ``reserves.params``."""
    values: dict[str, float] = {}
    for unit in case.units:
        for item in unit.components:
            values[res_params.density_key(unit.code, item.code)] = item.density_t_m3
            values[res_params.swell_key(unit.code, item.code)] = item.swell
            values[res_params.percent_key(unit.code, item.code)] = item.percent
        if not unit.components:
            values[res_params.density_key(unit.code)] = unit.density_t_m3
            values[res_params.swell_key(unit.code)] = unit.swell
    return values


def _weigh(case, column) -> object:
    """Las toneladas de la columna ``column`` con los m³ por unidad que da el núcleo sobre
    ``case`` (la fila de todos, sin rodajas)."""
    result = _cubicate(case)
    volumes = [tonnage.UnitVolume(tonnage.ALL_DOMAINS, None, unit.code, float(volume))
               for unit, volume in zip(case.units, result.unit_volume_m3[kernel.ALL],
                                       strict=True)]
    return tonnage.tonnage(volumes, column, _parameters(case))


class StockpileWeightTest(unittest.TestCase):
    """CE-011-03 (RF-011-15, RF-011-16): lo suelto se pesa con la densidad suelta."""

    def assertRelative(self, found: float | None, expected: float) -> None:
        self.assertIsNotNone(found)
        self.assertLessEqual(abs(found - expected), TOLERANCE * abs(expected),
                             f"{found!r} frente a {expected!r}")

    def test_a_stockpile_weighs_v_rho_over_k(self) -> None:
        """CE-011-03 (error 67): el acopio, suelto, de V = 3.600 m³ (ρ 2,60 t/m³, K 1,50) pesa
        V·ρ/K = 6.240 t; con la densidad in situ (el mismo acopio, in situ) habría pesado K
        veces más, 9.360 t. Las demás unidades, su analítico: lo in situ, V·ρ; el escombro
        (suelto), V·ρ/K; la capa útil, por sus porcentajes, con sus componentes que suman la
        unidad; el total de toneladas, la suma (todo ≤ 10⁻⁹)."""
        case = fx.material_column()
        column = fx.domain_column(case)
        found = _weigh(case, column)
        stockpile = case.units[0]
        self.assertEqual((stockpile.code, stockpile.state), ("acopio", "loose"))
        loose_t = found.row("acopio").mass_t
        self.assertRelative(loose_t, 3_600.0 * 2.60 / 1.50)
        self.assertRelative(loose_t, 6_240.0)
        units = list(column.units)
        units[0] = dataclasses.replace(units[0], state="in_situ")
        in_situ_t = _weigh(case, materials.MaterialColumn(tuple(units))).row("acopio").mass_t
        self.assertRelative(in_situ_t, 9_360.0)
        self.assertRelative(in_situ_t / loose_t, stockpile.swell)

        expected_total = []
        for unit in case.units:
            elements = [(unit, None)] if not unit.components else [
                (unit, item) for item in unit.components]
            for owner, item in elements:
                source = owner if item is None else item
                expected = source.expected_m3 * source.density_t_m3
                if owner.state == "loose":
                    expected /= source.swell
                expected_total.append(expected)
                with self.subTest(unit=owner.code, component=None if item is None else item.code):
                    row = found.row(owner.code, None if item is None else item.code)
                    self.assertRelative(row.volume_m3, source.expected_m3)
                    self.assertRelative(row.mass_t, expected)
            if unit.components:
                parts = sum(found.row(unit.code, item.code).volume_m3 for item in unit.components)
                self.assertRelative(parts, found.row(unit.code).volume_m3)
        self.assertRelative(found.total.total_t, sum(expected_total))
        self.assertEqual(found.missing, ())


if __name__ == "__main__":
    unittest.main()
