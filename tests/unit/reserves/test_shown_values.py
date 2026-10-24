# SPDX-License-Identifier: GPL-3.0-or-later
"""Las cifras de la cubicación como las lee una persona (spec 011, T34; HU-011-1; RF-011-23,
RF-011-24; plan 011 §5.5, D-29).

En el H2, el panel de la cubicación enseñaba el valor guardado sin redondear («91 450,50000000001
m³», «1,5675253987838387 m³/m³»). ``reserves.table.quantity_text`` (y ``number_text``, sin la
unidad) da cada valor con los decimales de su unidad (``reserves.table.DECIMALS``: m³, m² y t,
sin decimales; las relaciones y los %, dos; las cotas, dos; el factor combinado, seis) con el
separador de miles y la coma decimal del idioma de Geoblender (``core.i18n.format_number``); es
lo que usan el panel, lo que dicen las órdenes y el aviso de los momentos. El CSV (RF-011-24,
D-29) sigue con el valor completo.
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

table = import_geoblender("reserves.table")
export = import_geoblender("reserves.export")
i18n = import_geoblender("core.i18n")
params_model = import_geoblender("core.params.model")

THIN = i18n.THIN_SPACE
LONG_M3 = 91_450.50000000001
"""El valor que enseñaba el panel en el H2 (m³)."""
LONG_RATIO = 1.5675253987838387
"""La relación estéril/útil que enseñaba el panel en el H2 (m³/m³)."""


def _export(*rows: object) -> object:
    """Una exportación mínima con las filas ``rows`` (``reserves.table.Row``)."""
    header = export.ExportHeader(
        cubication="Mensual", project="Proyecto", version="V01", version_status="VIGENTE",
        revision="V01.r1", revision_state="abierta", operations=(), inputs=(), parameters=(),
        exported_at="2026-10-24T10:00:00Z", geoblender_version="0.1.0")
    return export.CubicationExport(header, tuple(
        export.ExportRow("Cubicación", row, "", ()) for row in rows))


class ShownValuesTest(unittest.TestCase):
    """RF-011-23, RF-011-24: los decimales de cada unidad en lo que se lee; el CSV, completo."""

    def tearDown(self) -> None:
        i18n.set_language("es")

    def test_every_quantity_has_the_decimals_of_its_unit(self) -> None:
        """RF-011-23: cada dato de las tablas de ``res`` tiene los decimales de su unidad: m³, m²
        y t sin decimales; m³/m³, t/t y %, dos; m (la cota media), dos; el factor combinado
        (adimensional), seis. Ninguna unidad de más ni de menos."""
        self.assertEqual(dict(table.DECIMALS), {
            "m3": 0, "m2": 0, "t": 0, "m3/m3": 2, "t/t": 2, "%": 2, "m": 2, "-": 6})
        self.assertEqual(set(table.DECIMALS),
                         {quantity.unit for quantity in table.QUANTITIES.values()})

    def test_values_rounded_with_the_thousands_separator(self) -> None:
        """RF-011-23: el valor del H2, «91 451 m³» (espacio fino de miles, sin decimales), no
        «91 450,50000000001 m³»; la relación, «1,57 m³/m³»; las áreas y las toneladas, enteras;
        el factor combinado con seis decimales y sin símbolo; un −0,4 m³, «0 m³» (sin «-0»). En
        inglés, «91,451 m³» y «1.57 m³/m³»."""
        long_text = params_model.format_value(LONG_M3, "es")
        self.assertIn("50000000001", long_text)  # lo de antes: todas las cifras
        for value, unit, expected in (
                (LONG_M3, "m3", f"91{THIN}451 m³"),
                (LONG_RATIO, "m3/m3", "1,57 m³/m³"),
                (LONG_RATIO, "t/t", "1,57 t/t"),
                (2_812_345.678, "m2", f"2{THIN}812{THIN}346 m²"),
                (12_345.678, "t", f"12{THIN}346 t"),
                (-14.0, "m3", "-14 m³"),
                (-0.4, "m3", "0 m³"),
                (1.0001823456, "-", "1,000182"),
                (-0.018234, "%", "-0,02 %"),
                (612.3456, "m", "612,35 m")):
            with self.subTest(valor=value, unidad=unit):
                self.assertEqual(table.quantity_text(value, unit), expected)
        self.assertEqual(table.number_text(LONG_M3, "m3"), f"91{THIN}451")
        self.assertEqual(table.number_text(LONG_RATIO, "t/t"), "1,57")
        i18n.set_language("en")
        self.assertEqual(table.quantity_text(LONG_M3, "m3"), "91,451 m³")
        self.assertEqual(table.quantity_text(LONG_RATIO, "m3/m3"), "1.57 m³/m³")

    def test_refuses_what_is_not_a_figure_of_the_tables(self) -> None:
        """Un valor que no es finito (las tablas nunca lo tienen: RF-011-22) o una unidad que no
        es de las tablas de ``res``: ``ValueError`` (un fallo del programa, no un texto)."""
        for value, unit in ((float("nan"), "m3"), (float("inf"), "t"), (1.0, "kg"),
                            (True, "m3")):
            with self.subTest(valor=value, unidad=unit), self.assertRaises(ValueError):
                table.quantity_text(value, unit)

    def test_csv_keeps_the_full_value(self) -> None:
        """RF-011-24 (D-29): el CSV escribe el valor completo, con coma decimal y sin separador de
        miles (el decimal más corto que vuelve al mismo float64), no el redondeado del panel."""
        found = export.csv_rows(_export(table.row("cut_m3", LONG_M3),
                                        table.row("waste_ratio_m3", LONG_RATIO)))
        values = [item[9] for item in found[-2:]]
        self.assertEqual(values, ["91450,50000000001", "1,5675253987838387"])


if __name__ == "__main__":
    unittest.main()
