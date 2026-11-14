# SPDX-License-Identifier: GPL-3.0-or-later
"""Los tres privados de la 014 que la 015 promueve a públicos (spec 015, T05; RF-015-13,
RF-015-19, RF-015-22; plan 015 §5.1 y §5.4 A1 y A3).

La plataforma (T06 a T09) calcula con lo que ya hacía la 014 y no lo reescribe: solo cambia el
nombre y la exportación, **sin cambio de comportamiento**.

- ``design.quarry.axis_abscissa`` (era ``_corridor_sigma``; A1): la abscisa ``σ`` de cada celda de
  una ventana, a lo largo de un eje de varios tramos (el punto más próximo de **todo** el eje; a
  igual distancia, el tramo anterior: la menor), y la abscisa sin recortar.
- ``design.edges.seed_envelope_steps`` (era ``_envelope_work``; A3): las unidades de la envolvente
  de la 013 desde unas semillas, con la métrica y la pendiente que se pidan. ``quarry`` tenía una
  copia idéntica (``_envelope_work``, solo cambiaba el nombre de un parámetro) y ``refit`` la
  importaba de ``edges``: queda **una sola** fuente, la de ``edges``.
- ``design.store.created_step_steps`` (era ``_created_step_steps``; A3): el salto creado de una
  superficie de diseño en el resumen de su diseño.

Las pruebas dicen que los tres son públicos (en ``__all__``, con su documentación), que los nombres
privados ya no existen en ningún módulo y que ``axis_abscissa`` da lo que daba ``_corridor_sigma``:
las cifras del eje en L de la cantera sintética (CE-014-03) que se midieron con ella antes de
renombrarla, la de cada celda del corredor a mano, su acuerdo con las cotas de ``corridor_cells`` y
el desempate de un eje que vuelve sobre sí mismo.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
edges = import_geoblender("design.edges")
refit = import_geoblender("design.refit")
store = import_geoblender("design.store")
model = import_geoblender("design.model")
vector = import_geoblender("gis.vector")

PROMOTED = ((quarry, "axis_abscissa"), (edges, "seed_envelope_steps"),
            (store, "created_step_steps"))
"""Lo que se promueve: el módulo y el nombre público."""
PRIVATE_NAMES = ("_corridor_sigma", "_envelope_work", "_created_step_steps")
"""Los nombres antiguos, que ya no existen en ningún módulo de ``design``."""
HALF_M = 10.0
"""La mitad del ancho del corredor en L de la cantera (m)."""
GRADIENT = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho",
                                start_level_field="cota_inicial", gradient_field="pendiente")
WHOLE = (slice(0, qfx.GRID.nrows), slice(0, qfx.GRID.ncols))
"""La ventana que es la rejilla entera."""
SUB_WINDOW = (slice(100, 260), slice(180, 340))
"""Una ventana que corta el corredor en L (filas 100 a 259, columnas 180 a 339)."""

# Lo que dio ``_corridor_sigma`` con el eje en L de la cantera (``qfx.CORRIDOR_AXIS_LOCAL``), medio
# ancho de 10 m y la rejilla de 1 m, ANTES de renombrarla (T05): las celdas dentro, la suma de σ
# y la de la abscisa sin recortar (sumas exactas: todo son múltiplos de 0,5 m), sus extremos y las
# celdas donde difieren (la unión redonda de fuera del vértice); y lo mismo en ``SUB_WINDOW``.
BEFORE_CELLS = 3979
BEFORE_SIGMA_SUM = 397_430.0
BEFORE_REACH_SUM = 397_766.5
BEFORE_SIGMA_RANGE = (0.5, 199.5)
BEFORE_DIFFER = 79
BEFORE_SUB_CELLS = 2779
BEFORE_SUB_SIGMA_SUM = 193_430.0


def broken_paths() -> list[np.ndarray]:
    """El eje en L de la cantera como lo recibe ``axis_abscissa``: un camino absoluto float64
    ``(3, 2)`` (120 m al este y 80 m al sur)."""
    return [cfx.absolute(qfx.CORRIDOR_AXIS_LOCAL)]


def corridor_layer() -> Any:
    """La capa de líneas con el eje en L, su ancho y su rasante, como la escribe
    ``write_feature_layer`` (un solo corredor, fid 1)."""
    columns = (vector.FieldColumn("ancho", "ancho", "DOUBLE"),
               vector.FieldColumn("cota_inicial", "cota_inicial", "DOUBLE"),
               vector.FieldColumn("pendiente", "pendiente", "DOUBLE"))
    values = {"ancho": (qfx.CORRIDOR_WIDTH_M,), "cota_inicial": (qfx.CORRIDOR_START_M,),
              "pendiente": (qfx.CORRIDOR_GRADIENT_PCT,)}
    return vector.FeatureLayer("line", (1,), (((broken_paths()[0],),),), columns, values)


class PublicNamesTest(unittest.TestCase):
    """RF-015-13, RF-015-19, RF-015-22: los tres nombres son públicos y los privados ya no están."""

    def test_the_three_names_are_public_and_documented(self) -> None:
        """Cada nombre está en el ``__all__`` de su módulo, es una función definida en él y
        tiene documentación."""
        for module, name in PROMOTED:
            with self.subTest(module=module.__name__, name=name):
                self.assertIn(name, module.__all__)
                function = getattr(module, name)
                self.assertTrue(callable(function))
                self.assertEqual(function.__module__, module.__name__)
                self.assertTrue(function.__doc__ and function.__doc__.strip())

    def test_the_private_names_are_gone(self) -> None:
        """Ni ``quarry``, ni ``edges``, ni ``refit``, ni ``store`` conservan el nombre antiguo (sin
        alias «por si acaso»)."""
        for module in (quarry, edges, refit, store):
            for name in PRIVATE_NAMES:
                with self.subTest(module=module.__name__, name=name):
                    self.assertFalse(hasattr(module, name))

    def test_the_envelope_work_has_a_single_source(self) -> None:
        """La envolvente de la 013 desde unas semillas la define ``edges``: ``quarry`` y ``refit``
        usan esa misma función, no una copia."""
        self.assertIs(quarry.seed_envelope_steps, edges.seed_envelope_steps)
        self.assertIs(refit.seed_envelope_steps, edges.seed_envelope_steps)
        self.assertNotIn("seed_envelope_steps", quarry.__all__)  # solo la define ``edges``


class AxisAbscissaTest(unittest.TestCase):
    """RF-015-19 (A1): ``axis_abscissa`` da lo que daba ``_corridor_sigma`` en un eje de varios
    tramos."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sigma, cls.reach = quarry.axis_abscissa(broken_paths(), HALF_M, qfx.GRID, WHOLE)
        cls.x, cls.y = qfx.local_centers()

    def test_same_figures_as_before_the_rename(self) -> None:
        """Las cifras que dio ``_corridor_sigma`` con el eje en L (CE-014-03): 3.979 celdas
        dentro (2.400 + 1.600 − 100 + 79), la suma de σ y la de la abscisa sin recortar, sus
        extremos (0,5 y 199,5 m), las 79 celdas donde la abscisa sin recortar difiere de σ y, en
        una ventana que corta el corredor, lo mismo (la ventana no cambia la abscisa)."""
        inside = np.isfinite(self.sigma)
        self.assertEqual(self.sigma.shape, qfx.GRID.shape)
        np.testing.assert_array_equal(inside, np.isfinite(self.reach))
        self.assertEqual(int(inside.sum()), BEFORE_CELLS)
        self.assertEqual(math.fsum(self.sigma[inside].tolist()), BEFORE_SIGMA_SUM)
        self.assertEqual(math.fsum(self.reach[inside].tolist()), BEFORE_REACH_SUM)
        self.assertEqual((float(self.sigma[inside].min()), float(self.sigma[inside].max())),
                         BEFORE_SIGMA_RANGE)
        self.assertEqual(int((inside & (self.sigma != self.reach)).sum()), BEFORE_DIFFER)
        sigma, reach = quarry.axis_abscissa(broken_paths(), HALF_M, qfx.GRID, SUB_WINDOW)
        found = np.isfinite(sigma)
        self.assertEqual(sigma.shape, (160, 160))
        self.assertEqual((int(found.sum()), math.fsum(sigma[found].tolist())),
                         (BEFORE_SUB_CELLS, BEFORE_SUB_SIGMA_SUM))
        np.testing.assert_array_equal(sigma, self.sigma[SUB_WINDOW])
        np.testing.assert_array_equal(reach, self.reach[SUB_WINDOW])

    def test_the_abscissa_follows_the_axis_cell_by_cell(self) -> None:
        """A mano: en el primer tramo, ``x − 200``; en el segundo, ``120 + (160 − y)``; en el cuarto
        de círculo de la esquina, el vértice (120 m) y la abscisa sin recortar pasa de él (125,5 m
        en la celda (325,5; 165,5)); fuera del corredor, ``NaN``."""
        def at(x: float, y: float, grid: np.ndarray) -> float:
            return float(grid[(self.x == x) & (self.y == y)][0])

        for (x, y), expected in (((200.5, 160.5), 0.5), ((250.5, 151.5), 50.5),
                                 ((325.5, 100.5), 179.5), ((310.5, 80.5), 199.5),
                                 ((325.5, 165.5), 120.0)):
            with self.subTest(cell=(x, y)):
                self.assertEqual(at(x, y, self.sigma), expected)
        self.assertEqual(at(325.5, 165.5, self.reach), 125.5)
        for x, y in ((199.5, 160.5), (320.5, 79.5), (329.5, 169.5)):
            with self.subTest(outside=(x, y)):
                self.assertTrue(math.isnan(at(x, y, self.sigma)))
                self.assertTrue(math.isnan(at(x, y, self.reach)))

    def test_it_agrees_with_the_levels_of_corridor_cells(self) -> None:
        """Lo que usa la plataforma: ``corridor_cells`` da a cada celda ``cota inicial + σ ·
        pendiente / 100`` con esa σ, y solo dentro de las celdas de ``axis_abscissa`` (a ≤
        10⁻⁹ m)."""
        found = quarry.corridor_cells(corridor_layer(), GRADIENT, qfx.GRID)
        inside = np.isfinite(found.floors.grid)
        np.testing.assert_array_equal(inside, np.isfinite(self.sigma))
        expected = (qfx.CORRIDOR_START_M
                    + self.sigma[inside] * qfx.CORRIDOR_GRADIENT_PCT / 100.0)
        np.testing.assert_allclose(found.floors.grid[inside], expected, rtol=0, atol=1e-9)

    def test_a_tie_between_two_stretches_takes_the_lower_abscissa(self) -> None:
        """Un eje que vuelve sobre sí mismo (este, norte y oeste, 6 m de ancho): una celda a igual
        distancia de la ida y de la vuelta toma el tramo anterior, la menor abscisa (A1: «a igual
        distancia, la menor»). A mano: la ida va por ``y = 200``, la vuelta por ``y = 211`` (σ de
        la vuelta, 111 + 200 − x), y el centro de las celdas de la fila ``y = 205,5`` equidista
        (5,5 m) de las dos: σ = x − 100 (la ida), no 311 − x."""
        path = cfx.absolute(((100.0, 200.0), (200.0, 200.0), (200.0, 211.0), (100.0, 211.0)))
        sigma, _ = quarry.axis_abscissa([path], 6.0, qfx.GRID, WHOLE)
        along = (self.x > 101.0) & (self.x < 190.0)  # lejos del tramo del norte (x = 200)
        row = (self.y == 205.5) & along
        self.assertEqual(int(row.sum()), 89)
        np.testing.assert_array_equal(sigma[row], self.x[row] - 100.0)
        # Fuera del empate, cada celda toma el más próximo: junto a la ida, la ida; junto a la
        # vuelta, la vuelta.
        near_out = (self.y == 201.5) & along
        near_back = (self.y == 209.5) & along
        np.testing.assert_array_equal(sigma[near_out], self.x[near_out] - 100.0)
        np.testing.assert_array_equal(sigma[near_back], 311.0 - self.x[near_back])


if __name__ == "__main__":
    unittest.main()
