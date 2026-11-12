# SPDX-License-Identifier: GPL-3.0-or-later
"""Los corredores de la cantera (spec 014, T09; HU-014-2; RF-014-09, RF-014-10; plan 014 A6,
§5.3.1; CE-014-03).

- ``design.quarry.corridor_cells``: cada corredor de una capa de líneas (eje, ancho en m y una cota
  fija o una rasante: cota inicial en m y pendiente en %) convertido en un fondo con **extremos
  planos**, perpendiculares al eje: dentro, las celdas a ≤ ancho/2 de algún tramo cuya proyección
  no cae antes del principio ni después del final del eje; su longitud medida (máximo menos mínimo
  de la abscisa ``σ`` de sus celdas) es la del eje con error ≤ 1 celda (error 20: 200 m, no 220 m).
- La cota de cada celda: la fija, o ``cota inicial + σ · pendiente / 100`` a ≤ 10⁻⁹ m.
- Un eje quebrado (el corredor en L de la cantera sintética): la abscisa sigue el eje y la
  longitud medida, la del eje.
- ``design.quarry.corridor_too_long``: el aviso de RF-014-10 con las dos longitudes en m.
- Los rechazos: ancho ≤ 0 (``des.corridor_width``), eje de longitud cero
  (``des.corridor_length_zero``), sin cota (``des.corridor_level_missing``), capa que no es de
  líneas (``des.corridor_not_lines``), campo que falta (``des.quarry_layer_field``) y dos
  corredores que se solapan, como dos fondos (``des.floor_overlap``, RF-014-06).

Sobre la rejilla de la cantera sintética de ``tests.support.quarry_fixtures`` (T01), sin proyecto
(la capa se arma como la escribe ``write_feature_layer``).
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
vector = import_geoblender("gis.vector")

TOLERANCE_M = 1e-9
FIXED = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", level_field="cota")
GRADED = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                              grade_field="pendiente")
STRAIGHT = ((100.0, 200.0), (300.0, 200.0))
"""Un eje recto de 200 m hacia el este (local), sobre bordes de celda."""


def corridor_layer(paths: tuple[tuple[tuple[float, float], ...], ...], **fields: tuple[Any, ...],
                   ) -> Any:
    """Una capa de líneas (``FeatureLayer``) con un eje local por entidad (fids 1…n), el campo
    ``nombre`` y los campos numéricos ``fields`` (campo → valor por entidad)."""
    parts = tuple(((cfx.absolute(path),),) for path in paths)
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               *(vector.FieldColumn(name, name, "DOUBLE") for name in fields))
    values = {"nombre": tuple(f"Corredor {index}" for index in range(1, len(paths) + 1)),
              **fields}
    return vector.FeatureLayer("line", tuple(range(1, len(paths) + 1)), parts, columns, values)


def fixture_layer() -> Any:
    """La capa de corredores de la cantera (el eje en L de 200 m con su rasante)."""
    data = next(item for item in qfx.layers() if item.name == qfx.CORRIDORS_LAYER)
    paths = tuple(tuple(map(tuple, (part[0] - np.asarray(cfx.BASE)).tolist()))
                  for entity in data.entities for part in entity)
    return corridor_layer(paths, **data.fields)


class StraightCorridorTest(unittest.TestCase):
    """RF-014-09, CE-014-03: un corredor recto de 200 m de eje y 20 m de ancho."""

    def test_flat_ends_and_length(self) -> None:
        """Las celdas son exactamente las del rectángulo de 200 × 20 m (4.000, extremos planos:
        ni media circunferencia en cada punta) y mide 200 m ± 1 celda, no 220 m."""
        layer = corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(150.0,))
        found = quarry.corridor_cells(layer, FIXED, qfx.GRID)
        inside = np.isfinite(found.floors.grid)
        np.testing.assert_array_equal(inside, qfx.in_box((100.0, 190.0, 300.0, 210.0)))
        self.assertEqual(found.floors.cells, (4000,))
        self.assertEqual(found.axes_m, (200.0,))
        self.assertEqual(found.widths_m, (20.0,))
        self.assertLessEqual(abs(found.lengths_m[0] - 200.0), qfx.GRID.dx)
        self.assertEqual(found.notices, ())
        np.testing.assert_array_equal(found.floors.grid[inside], 150.0)
        self.assertEqual(found.floors.levels, (150.0,))
        self.assertEqual((found.floors.layer, found.floors.field), (qfx.CORRIDORS_LAYER, "cota"))
        np.testing.assert_array_equal(found.floors.owner, inside.astype(np.int32))

    def test_grade_level(self) -> None:
        """Con rasante, cada celda a ``cota inicial + σ · pendiente / 100`` a ≤ 10⁻⁹ m (σ, la
        distancia del centro al principio del eje, medida a lo largo de él)."""
        layer = corridor_layer((STRAIGHT,), ancho=(20.0,), cota_inicial=(125.0,),
                               pendiente=(-3.0,))
        found = quarry.corridor_cells(layer, GRADED, qfx.GRID)
        x, _ = qfx.local_centers()
        inside = np.isfinite(found.floors.grid)
        expected = 125.0 + (x[inside] - 100.0) * -3.0 / 100.0
        np.testing.assert_allclose(found.floors.grid[inside], expected, rtol=0, atol=TOLERANCE_M)
        self.assertEqual(found.floors.field, "cota_inicial")

    def test_input_not_modified(self) -> None:
        """La capa no se modifica."""
        layer = corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(150.0,))
        before = layer.parts[0][0][0].copy()
        quarry.corridor_cells(layer, FIXED, qfx.GRID)
        np.testing.assert_array_equal(layer.parts[0][0][0], before)


class BrokenAxisTest(unittest.TestCase):
    """RF-014-09, A6: el corredor en L de la cantera (120 m al este y 80 m al sur, rasante de 8 %
    desde 125 m)."""

    def setUp(self) -> None:
        self.found = quarry.corridor_cells(fixture_layer(), GRADED, qfx.GRID)
        self.x, self.y = qfx.local_centers()

    def cell(self, x: float, y: float) -> float:
        """La cota del corredor en la celda del centro local ``(x, y)``."""
        hit = (self.x == x) & (self.y == y)
        return float(self.found.floors.grid[hit][0])

    def test_length_of_the_axis(self) -> None:
        """Mide 200 m ± 1 celda (CE-014-03 sobre la cantera) y no avisa."""
        self.assertEqual(self.found.axes_m, (qfx.CORRIDOR_LENGTH_M,))
        self.assertLessEqual(abs(self.found.lengths_m[0] - qfx.CORRIDOR_LENGTH_M), qfx.GRID.dx)
        self.assertEqual(self.found.notices, ())

    def test_cells(self) -> None:
        """Las celdas: los dos rectángulos (120 × 20 y 20 × 80 m, con 10 × 10 comunes) y, en la
        esquina exterior, el cuarto de círculo de 10 m de radio alrededor del vértice (contado a
        mano celda a celda); nada antes del principio ni después del final."""
        corner = sum(1 for i in range(10) for j in range(10)
                     if (i + 0.5) ** 2 + (j + 0.5) ** 2 <= 100.0)
        self.assertEqual(self.found.floors.cells, (2400 + 1600 - 100 + corner,))
        for x, y in ((199.5, 160.5), (320.5, 79.5), (329.5, 169.5)):
            self.assertTrue(np.isnan(self.cell(x, y)), (x, y))
        for x, y in ((200.5, 169.5), (329.5, 80.5), (320.5, 160.5)):
            self.assertFalse(np.isnan(self.cell(x, y)), (x, y))

    def test_grade_follows_the_axis(self) -> None:
        """La abscisa sigue el eje: en el primer tramo, ``x − 200``; en el segundo, ``120 + (160 −
        y)``; en el cuarto de círculo de la esquina, la del vértice (120 m). Cotas a ≤ 10⁻⁹ m."""
        grade = qfx.CORRIDOR_GRADE_PCT / 100.0
        start = qfx.CORRIDOR_START_M
        for (x, y), sigma in (((200.5, 160.5), 0.5), ((250.5, 151.5), 50.5),
                              ((325.5, 100.5), 179.5), ((310.5, 80.5), 199.5),
                              ((325.5, 165.5), 120.0)):
            self.assertAlmostEqual(self.cell(x, y), start + sigma * grade, delta=TOLERANCE_M)


class NoticeTest(unittest.TestCase):
    """RF-014-10: el aviso de un corredor más largo que su eje más su ancho."""

    def test_too_long(self) -> None:
        """221 m con un eje de 200 m y 20 m de ancho avisa con las dos longitudes en m; 220 m, no."""
        text = quarry.corridor_too_long(3, 200.0, 221.0, 20.0)
        self.assertIsNotNone(text)
        self.assertIn("221 m", text)
        self.assertIn("200 m", text)
        self.assertIn("corredor 3", text)
        self.assertIsNone(quarry.corridor_too_long(3, 200.0, 220.0, 20.0))

    def test_map_notices(self) -> None:
        """Un ``CorridorMap`` con una longitud medida que pasa del eje más el ancho lo avisa."""
        found = quarry.corridor_cells(corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(150.0,)),
                                      FIXED, qfx.GRID)
        longer = quarry.CorridorMap(found.floors, found.widths_m, found.axes_m, (230.0,))
        self.assertEqual(longer.notices,
                         (quarry.corridor_too_long(1, 200.0, 230.0, 20.0),))


class RejectionTest(unittest.TestCase):
    """RF-014-09 y casos límite (§8): los rechazos nombran la capa, el corredor, el campo y el
    valor, y no suponen nada."""

    def rejected(self, layer: Any, fields: Any = FIXED) -> Any:
        """El ``DesignError`` de convertir ``layer``."""
        with self.assertRaises(messages.DesignError) as caught:
            quarry.corridor_cells(layer, fields, qfx.GRID)
        return caught.exception

    def test_width_not_positive(self) -> None:
        """Ancho 0, negativo, sin valor o no finito: ``des.corridor_width`` nombrando el campo."""
        for width in (0.0, -5.0, None, float("nan")):
            with self.subTest(width=width):
                error = self.rejected(corridor_layer((STRAIGHT, ((0.0, 0.0), (50.0, 0.0))),
                                                     ancho=(20.0, width), cota=(150.0, 150.0)))
                self.assertEqual(error.code, "des.corridor_width")
                self.assertEqual(error.values["field"], "ancho")
                self.assertEqual(error.values["corridor"], 2)
                self.assertEqual(error.values["layer"], qfx.CORRIDORS_LAYER)

    def test_length_zero(self) -> None:
        """Un eje de longitud cero: ``des.corridor_length_zero``."""
        error = self.rejected(corridor_layer((((100.0, 100.0), (100.0, 100.0)),),
                                             ancho=(20.0,), cota=(150.0,)))
        self.assertEqual(error.code, "des.corridor_length_zero")
        self.assertEqual(error.values["corridor"], 1)

    def test_level_missing(self) -> None:
        """Sin cota fija, sin cota inicial o sin pendiente: ``des.corridor_level_missing`` con el
        campo."""
        cases = ((FIXED, {"cota": (None,)}, "cota"),
                 (GRADED, {"cota_inicial": (float("inf"),), "pendiente": (5.0,)}, "cota_inicial"),
                 (GRADED, {"cota_inicial": (125.0,), "pendiente": (None,)}, "pendiente"))
        for fields, values, field in cases:
            with self.subTest(field=field):
                error = self.rejected(corridor_layer((STRAIGHT,), ancho=(20.0,), **values),
                                      fields)
                self.assertEqual(error.code, "des.corridor_level_missing")
                self.assertEqual(error.values["field"], field)

    def test_not_lines(self) -> None:
        """Una capa de polígonos: ``des.corridor_not_lines``."""
        layer = vector.FeatureLayer("polygon", (1,), ((cfx.rectangle(0.0, 0.0, 10.0, 10.0),),),
                                    (vector.FieldColumn("ancho", "ancho", "DOUBLE"),),
                                    {"ancho": (20.0,)})
        error = self.rejected(layer)
        self.assertEqual(error.code, "des.corridor_not_lines")
        self.assertEqual(error.values["value"], "polígonos")

    def test_missing_field(self) -> None:
        """Un campo que la capa no tiene: ``des.quarry_layer_field``."""
        error = self.rejected(corridor_layer((STRAIGHT,), ancho=(20.0,), altura=(150.0,)))
        self.assertEqual(error.code, "des.quarry_layer_field")
        self.assertEqual(error.values["value"], "cota")

    def test_overlap(self) -> None:
        """Dos corredores que se cruzan son dos fondos que se solapan (RF-014-06):
        ``des.floor_overlap`` con los dos."""
        error = self.rejected(corridor_layer((STRAIGHT, ((200.0, 100.0), (200.0, 300.0))),
                                             ancho=(20.0, 10.0), cota=(150.0, 150.0)))
        self.assertEqual(error.code, "des.floor_overlap")
        self.assertEqual((error.values["value"], error.values["other"]), (1, 2))
        self.assertEqual(error.values["cells"], 200)


if __name__ == "__main__":
    unittest.main()
