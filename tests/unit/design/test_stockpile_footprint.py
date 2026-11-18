# SPDX-License-Identifier: GPL-3.0-or-later
"""La huella de un acopio, sus avisos y el reparto de las celdas comunes (spec 016, T07; RF-016-02, RF-016-04,
RF-016-05, RF-016-06; CE-016-02; E1; plan 016 A3 y §5.4).

:mod:`design.stockpiles` forma la huella de una marca (la zona conexa mayor que toca la marca, dentro de la marca
ampliada por su margen, de las celdas cuyo terreno queda más que el umbral sobre el plano, con los huecos rellenos),
repite el plano de A2 con la huella nueva hasta que no cambia o se acaban las vueltas, mide su volumen y reparte las
celdas que comparten las huellas de dos marcas. Se prueba con:

- **cuentas a mano**: el volumen de un tronco de pirámide (129 m³), el de uno con un cráter (97 m³), las áreas y las
  celdas comunes de los casos pequeños, contadas sobre el papel;
- **implementaciones independientes** (``tests.support.design_oracles``: bucles de Python y búsquedas en anchura, sin
  ``design.grids`` ni ``design.morphology``): ``hand_dilate``, ``hand_zones``, ``hand_footprint``, ``hand_volume`` y
  ``hand_share``, que con los de A2 (``hand_crown``, ``hand_cell_slope_deg``, ``hand_plane``) hacen **todo A2 y A3 a
  mano** en :func:`hand_grow`;
- la **cantera de la 016** (``tests.support.stockpile_data``): el cono de CE-016-02 con sus celdas atípicas y los dos
  acopios que se tocan de E1.
"""

from __future__ import annotations

import math
import time
import unittest
from contextlib import closing
from dataclasses import dataclass

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
stockpiles = import_geoblender("design.stockpiles")
morphology = import_geoblender("design.morphology")

THRESHOLD_M = 0.3
"""El umbral de huella de la 011 (``res.anthropic_presence_m``, D-17): lo lee la detección por su clave; aquí, un
valor de ENTRADA."""
MARGIN_M = 10.0
TURNS = 6
# Los umbrales de D-3 (ADOPTADO «sin confirmar»; la inclinación máxima y el cuantil, HIPÓTESIS): valores de ENTRADA de
# estas pruebas, no los que la implementación da por defecto (no da ninguno: P-6 del plan, «sin cifras a mano»).
D3 = {"crown_inner_m": 1.0, "crown_outer_m": 3.0, "crown_slope_deg": 12.0, "crown_flat_min_m2": 10.0,
      "max_residual_m": 1.0, "fit_rounds": 4, "tilt_max_deg": 4.0, "support_quantile": 0.6}
AT_EDGE = "des.stockpile_footprint_at_edge"
SEVERAL = "des.stockpile_several_zones"
FEW_FLAT = "des.stockpile_crown_few_flat"
TILT = "des.stockpile_tilt_limited"
NOT_CONVERGED = "des.stockpile_not_converged"
SHARED = "des.stockpile_shared_cells"
NO_CELLS = "des.stockpile_no_cells"
NO_TERRAIN = "des.stockpile_no_terrain"


def params_of(*, margin_m: float = MARGIN_M, turns: int = TURNS, threshold_m: float = THRESHOLD_M,
              **plane: float) -> object:
    """Los parámetros de A3 con los umbrales de D-3 (y los cambios de ``plane``)."""
    return stockpiles.FootprintParams(plane=stockpiles.PlaneParams(**{**D3, **plane}), margin_m=margin_m,
                                      turns=turns, threshold_m=threshold_m)


def cells_of(grid: object, z: np.ndarray, mask: np.ndarray) -> list[tuple[float, float, float]]:
    """``(x, y, z)`` de las celdas de ``mask`` en el orden de lectura (fila 0 al norte), para el oráculo."""
    x, y = grid.centers()
    return [(float(x[r, c]), float(y[r, c]), float(z[r, c])) for r, c in np.argwhere(mask)]


def centre(grid: object, cells: object) -> tuple[float, float]:
    """El centro (media de los centros de celda, a mano con ``fsum``) de las celdas ``(fila, columna)`` de ``cells``."""
    x, y = grid.centers()
    cells = list(cells)
    return (math.fsum(float(x[r, c]) for r, c in cells) / len(cells),
            math.fsum(float(y[r, c]) for r, c in cells) / len(cells))


def where(grid: object, row: int, col: int) -> tuple[float, float]:
    """El centro (absoluto) de la celda ``(row, col)``."""
    x, y = grid.centers()
    return float(x[row, col]), float(y[row, col])


def rect(shape: tuple[int, int], rows: tuple[int, int], cols: tuple[int, int]) -> np.ndarray:
    """Una máscara de ``shape`` con las filas ``rows[0] … rows[1]`` y las columnas ``cols[0] … cols[1]``
    (ambas incluidas)."""
    found = np.zeros(shape, dtype=bool)
    found[rows[0]:rows[1] + 1, cols[0]:cols[1] + 1] = True
    return found


def values_of(notes: object, code: str) -> dict[str, object]:
    """Los valores de la única nota de ``notes`` con ese ``code``."""
    found = [note for note in notes if note.code == code]
    assert len(found) == 1, f"{code}: {len(found)} notas en {[note.code for note in notes]}"
    return dict(found[0].values)


def codes_of(notes: object) -> list[str]:
    return [note.code for note in notes]


# --- Los casos pequeños ------------------------------------------------------------------------------------

SMALL_SIZE_M = 30.0
SMALL_MARK_BOX = (7.0, 7.0, 23.0, 23.0)
"""La marca de los casos pequeños (local): 16 × 16 m, centrada en el montón."""


@dataclass(frozen=True, slots=True, eq=False)
class Scene:
    """Un montón de la ventana de 30 × 30 m: la ``grid``, el plano (``base``), la altura del montón (``height``), el
    terreno (``terrain``) y la marca (``mark``, máscara)."""

    grid: object
    base: np.ndarray
    height: np.ndarray
    terrain: np.ndarray
    mark: np.ndarray


def small_scene(shape: str = "cone", tilt_deg: float = 3.0, *, blocks: tuple = (), flatten: tuple = ()) -> Scene:
    """Un tronco de ``shape`` (pie de 6 m, cima de 2 m y 2 m de altura: pendiente 0,5) sobre un plano de ``tilt_deg``
    ° en una ventana de 30 × 30 m de celdas de 1 m. ``blocks`` son ``(caja local, +m)`` que se suman al terreno (una
    celda atípica es una caja de 1 m en torno a su centro) y ``flatten``, cajas que se dejan a la altura del plano
    (un cráter). La marca es :data:`SMALL_MARK_BOX`."""
    grid = sdata.window_grid(1.0, SMALL_SIZE_M)
    mound = sdata.Mound("pequeño", shape, 15.0, 15.0, 6.0, 2.0, 2.0)
    base = sdata.plane(tilt_deg, pivot=(15.0, 15.0)).values(grid)
    height = sdata.mound_heights(grid.shape, 1.0, (mound,))
    terrain = base + height
    for box, delta in blocks:
        terrain[sdata.in_box(box, grid)] += delta
    for box in flatten:
        terrain[sdata.in_box(box, grid)] = base[sdata.in_box(box, grid)]
    return Scene(grid, base, height, terrain, sdata.in_box(SMALL_MARK_BOX, grid))


def spike(x: float, y: float, delta: float) -> tuple[tuple[float, float, float, float], float]:
    """Un bloque atípico de una celda de 1 m en torno al centro de celda ``(x, y)`` (local)."""
    return ((x - 0.5, y - 0.5, x + 0.5, y + 0.5), delta)


SPIKES = (spike(25.5, 15.5, 3.0), spike(22.5, 8.5, 2.5), spike(4.5, 14.5, -2.0))
"""Tres celdas atípicas: una en la corona de la marca (+3 m), una dentro de la marca y aislada del montón (+2,5 m: una
zona más que toca la marca) y una en la corona por el oeste (−2 m)."""


@dataclass(frozen=True, slots=True, eq=False)
class HandGrown:
    """Lo que da :func:`hand_grow`: la huella a mano (``found``), el plano en la ventana (``base``) y su ``plane``, el
    volumen, las vueltas, si convergió, la huella de la vuelta anterior (``previous``) y si la corona no tenía celdas
    llanas bastantes (``few_flat``)."""

    found: object
    base: np.ndarray
    plane: object
    volume: float
    turns: int
    converged: bool
    previous: np.ndarray
    few_flat: bool


def hand_grow(z: np.ndarray, grid: object, mark: np.ndarray, *, margin_m: float, turns: int = TURNS,
              threshold: float = THRESHOLD_M) -> HandGrown:
    """A2 y A3 enteros **a mano**, con los oráculos independientes de ``design_oracles`` (bucles de Python): la marca
    ampliada, y en cada vuelta la corona, sus celdas llanas, el plano en racionales exactos y la huella por una
    búsqueda en anchura, hasta que no cambie o se acaben las vueltas."""
    cell = grid.dx
    rows, mark_rows = z.tolist(), mark.tolist()
    enlarged = oracles.hand_dilate(mark_rows, cell, margin_m)
    slope = oracles.hand_cell_slope_deg(rows, cell, cell)
    x, y = grid.centers()
    current, previous, converged, few_flat = mark.copy(), mark.copy(), False, False
    for turn in range(1, turns + 1):
        crown = oracles.hand_crown(current.tolist(), cell, D3["crown_inner_m"], D3["crown_outer_m"])
        flat = crown & (slope < D3["crown_slope_deg"])
        few_flat = float(flat.sum()) * cell * cell < D3["crown_flat_min_m2"]
        plane = oracles.hand_plane(cells_of(grid, z, crown if few_flat else flat), rounds=D3["fit_rounds"],
                                   max_residual_m=D3["max_residual_m"], tilt_max_deg=D3["tilt_max_deg"],
                                   quantile=D3["support_quantile"])
        base = np.array([[plane.at(float(x[r, c]), float(y[r, c])) for c in range(grid.ncols)]
                         for r in range(grid.nrows)])
        found = oracles.hand_footprint(rows, base.tolist(), mark_rows, enlarged.tolist(), threshold)
        assert found is not None, "el oráculo no encontró ninguna zona que toque la marca"
        if np.array_equal(found.mask, current):
            converged = True
            break
        previous, current = current, found.mask
    volume = oracles.hand_volume(rows, base.tolist(), found.mask.tolist(), cell * cell, threshold)
    return HandGrown(found, base, plane, volume, turn, converged, previous, few_flat)


def expected_codes(hand: HandGrown) -> list[str]:
    """Los códigos de las notas que A3 tiene que dar, por lo que vio el oráculo y en el orden documentado."""
    codes = []
    if hand.found.first_edge is not None:
        codes.append(AT_EDGE)
    if hand.found.zones > 1:
        codes.append(SEVERAL)
    if hand.few_flat:
        codes.append(FEW_FLAT)
    if hand.plane.limited:
        codes.append(TILT)
    if not hand.converged:
        codes.append(NOT_CONVERGED)
    return codes


class OracleTest(unittest.TestCase):
    """Los oráculos de A3 dan lo que se sabe antes de usarlos de árbitro."""

    def test_hand_zones_orders_by_first_cell_and_is_four_connected(self) -> None:
        """Una diagonal no une: tres zonas, en el orden de su primera celda recorriendo la rejilla fila a fila."""
        mask = [[True, False, False, True],
                [False, True, False, True],
                [False, False, False, False],
                [True, True, False, False]]
        self.assertEqual(oracles.hand_zones(mask), [((0, 0),), ((0, 3), (1, 3)), ((1, 1),), ((3, 0), (3, 1))])

    def test_hand_footprint_fills_the_hole_and_counts_the_zones_by_hand(self) -> None:
        """Un anillo de 4 × 4 con un hueco de 2 × 2: la huella son las 16 celdas; la isla del hueco, que toca la marca,
        se queda dentro y no cuenta como otra zona; la zona de fuera, que también la toca, sí."""
        z = np.zeros((8, 10))
        z[1:5, 1:5] = 1.0
        z[2:4, 2:4] = 0.0
        z[2, 2] = 1.0  # la isla
        z[6, 7] = 1.0  # otra zona
        mark = np.zeros((8, 10), dtype=bool)
        mark[1, 1], mark[2, 2], mark[6, 7] = True, True, True
        found = oracles.hand_footprint(z.tolist(), np.zeros((8, 10)).tolist(), mark.tolist(),
                                       np.ones((8, 10), dtype=bool).tolist(), 0.3)
        np.testing.assert_array_equal(found.mask, rect((8, 10), (1, 4), (1, 4)))
        self.assertEqual(found.zones, 2)
        self.assertEqual(found.other, ((6, 7),))
        self.assertIsNone(found.first_edge)

    def test_hand_share_follows_the_rule_by_hand(self) -> None:
        """Marca A en las columnas 0 a 4 y marca B en las 6 a 10 de una fila; las huellas se solapan en las columnas 3 a
        7. Las 3 y 4 son de A, la 6 y la 7, de B; la 5, en el hueco entre las dos marcas, equidista (1 celda cada
        una): gana la primera de la lista."""
        marks = [rect((1, 11), (0, 0), (0, 4)), rect((1, 11), (0, 0), (6, 10))]
        footprints = [rect((1, 11), (0, 0), (0, 7)), rect((1, 11), (0, 0), (3, 10))]
        first, second = oracles.hand_share(footprints, marks)
        np.testing.assert_array_equal(first, rect((1, 11), (0, 0), (0, 5)))
        np.testing.assert_array_equal(second, rect((1, 11), (0, 0), (6, 10)))
        second, first = oracles.hand_share(footprints[::-1], marks[::-1])
        np.testing.assert_array_equal(second, rect((1, 11), (0, 0), (6, 10)) | rect((1, 11), (0, 0), (5, 5)))


class FootprintAboveTest(unittest.TestCase):
    """:func:`stockpiles.footprint_above`: la zona sobre un plano dado, sin ajustar nada (RF-016-02, RF-016-04,
    RF-016-05, RF-016-03)."""

    SHAPE = (20, 20)

    def setUp(self) -> None:
        self.grid = sdata.window_grid(1.0, 20.0)
        self.base = np.zeros(self.SHAPE)
        self.everywhere = np.ones(self.SHAPE, dtype=bool)

    def cut(self, z: np.ndarray, mark: np.ndarray, enlarged: np.ndarray | None = None, **changes: object) -> object:
        return stockpiles.footprint_above(z, changes.get("base", self.base), mark,
                                          self.everywhere if enlarged is None else enlarged, self.grid,
                                          changes.get("threshold_m", THRESHOLD_M))

    def terrain(self, *zones: tuple[tuple[int, int], tuple[int, int], float]) -> np.ndarray:
        z = np.zeros(self.SHAPE)
        for rows, cols, height in zones:
            z[rows[0]:rows[1] + 1, cols[0]:cols[1] + 1] = height
        return z

    def test_the_footprint_is_the_largest_zone_that_touches_the_mark(self) -> None:
        """RF-016-02, RF-016-05: de dos zonas que tocan la marca (36 y 60 celdas) la huella es la mayor, y la otra se
        avisa con cuántas zonas hay y en torno a su centro (calculado a mano); una zona de 100 celdas que no toca la
        marca no cuenta."""
        z = self.terrain(((4, 9), (4, 9), 1.0), ((4, 13), (12, 17), 1.0), ((14, 19), (2, 11), 1.0))
        mark = rect(self.SHAPE, (5, 8), (6, 14))
        found = self.cut(z, mark)
        np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (4, 13), (12, 17)))
        by_hand = oracles.hand_footprint(z.tolist(), self.base.tolist(), mark.tolist(), self.everywhere.tolist(), 0.3)
        np.testing.assert_array_equal(found.mask, by_hand.mask)
        self.assertEqual(found.zones, 2)
        values = values_of(found.notes, SEVERAL)
        self.assertEqual(values["zones"], 2)
        x, y = centre(self.grid, [(r, c) for r in range(4, 10) for c in range(4, 10)])
        self.assertAlmostEqual(values["x"], x, delta=1e-6)
        self.assertAlmostEqual(values["y"], y, delta=1e-6)
        self.assertEqual(codes_of(found.notes), [SEVERAL])

    def test_a_tie_goes_to_the_zone_first_in_reading_order(self) -> None:
        """RF-016-05: con dos zonas del mismo tamaño gana la de la primera celda en el orden de lectura (norte a sur y,
        dentro de una fila, de oeste a este), y la otra se avisa: no es «la de más a la izquierda»."""
        upper_right = self.terrain(((1, 6), (12, 17), 1.0), ((10, 15), (2, 7), 1.0))
        mark = rect(self.SHAPE, (0, 19), (0, 19))
        found = self.cut(upper_right, mark)
        np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (1, 6), (12, 17)))
        x, y = centre(self.grid, [(r, c) for r in range(10, 16) for c in range(2, 8)])
        values = values_of(found.notes, SEVERAL)
        self.assertAlmostEqual(values["x"], x, delta=1e-6)
        self.assertAlmostEqual(values["y"], y, delta=1e-6)

    def test_the_place_of_the_zones_note_is_the_largest_of_the_others(self) -> None:
        """RF-016-05: con tres zonas que tocan la marca (de 60, 30 y 12 celdas), la huella es la de 60 y la nota dice 3
        zonas en torno al centro de la de 30, la mayor de las demás (a mano)."""
        z = self.terrain(((4, 13), (12, 17), 1.0), ((2, 4), (1, 10), 1.0), ((15, 17), (2, 5), 1.0))
        mark = np.zeros(self.SHAPE, dtype=bool)
        mark[5, 14] = mark[3, 5] = mark[16, 3] = True
        found = self.cut(z, mark)
        np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (4, 13), (12, 17)))
        values = values_of(found.notes, SEVERAL)
        x, y = centre(self.grid, [(r, c) for r in range(2, 5) for c in range(1, 11)])
        self.assertEqual(values["zones"], 3)
        self.assertAlmostEqual(values["x"], x, delta=1e-6)
        self.assertAlmostEqual(values["y"], y, delta=1e-6)

    def test_one_zone_gives_no_several_zones_note(self) -> None:
        """Una sola zona (con una isla de otra altura dentro de su hueco, que toca la marca y se queda dentro de la
        huella): ninguna nota."""
        z = self.terrain(((3, 12), (3, 12), 1.0), ((6, 9), (6, 9), 0.0))
        z[7, 7] = 1.0  # la isla
        mark = np.zeros(self.SHAPE, dtype=bool)
        mark[3, 3] = mark[7, 7] = True
        found = self.cut(z, mark)
        np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (3, 12), (3, 12)))
        self.assertEqual(found.zones, 1)
        self.assertEqual(found.notes, ())

    def test_holes_are_filled_and_only_their_volume_above_the_threshold_counts(self) -> None:
        """D-18: una meseta de 10 × 10 de 1 m con un hueco de 4 × 4 a la altura del plano: la huella tiene las 100
        celdas (el área cuenta el hueco: 100 m²) y el volumen, solo donde pasa del umbral, 84 m³; con el hueco a 0,3 m
        (justo en el umbral) tampoco cuenta."""
        mark = rect(self.SHAPE, (3, 3), (3, 3))
        for hole in (0.0, 0.3):
            z = self.terrain(((3, 12), (3, 12), 1.0), ((6, 9), (6, 9), hole))
            found = self.cut(z, mark)
            with self.subTest(hole=hole):
                np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (3, 12), (3, 12)))
                self.assertEqual(float(found.mask.sum()) * self.grid.cell_area, 100.0)
                self.assertEqual(stockpiles.footprint_volume(z, self.base, found.mask, self.grid.cell_area,
                                                             THRESHOLD_M), 84.0)
        z = self.terrain(((3, 12), (3, 12), 1.0), ((6, 9), (6, 9), 0.31))
        self.assertAlmostEqual(stockpiles.footprint_volume(z, self.base, self.cut(z, mark).mask,
                                                           self.grid.cell_area, THRESHOLD_M),
                               84.0 + 16 * 0.31, delta=1e-12)

    def test_a_footprint_with_a_hole_without_terrain_is_rejected_with_its_place(self) -> None:
        """RF-016-04: si un hueco que se rellena no tiene dato, falta terreno en la huella: el rechazo da cuántas
        celdas son y el lugar de la primera en el orden de lectura (absoluto); una celda sin dato en el borde de la
        zona, que no queda dentro de la huella, no rechaza nada."""
        mark = rect(self.SHAPE, (3, 3), (3, 3))
        z = self.terrain(((3, 12), (3, 12), 1.0))
        z[6, 7], z[6, 8], z[8, 6] = np.nan, np.nan, np.nan
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            self.cut(z, mark)
        self.assertEqual(caught.exception.message.code, NO_TERRAIN)
        values = dict(caught.exception.message.values)
        x, y = where(self.grid, 6, 7)
        self.assertEqual((values["cells"], values["x"], values["y"]), (3, x, y))
        edge = self.terrain(((3, 12), (3, 12), 1.0))
        edge[3, 12] = np.nan  # en el borde de la zona, no en un hueco
        found = self.cut(edge, mark)
        self.assertFalse(found.mask[3, 12])

    def test_a_mark_with_no_cell_above_the_threshold_is_rejected(self) -> None:
        """RF-016-04: sin ninguna zona que toque la marca (nada sobre el umbral, justo en el umbral o una zona que
        no la toca) el acopio se rechaza con el umbral; un valor justo por encima del umbral sí es una zona."""
        mark = rect(self.SHAPE, (3, 5), (3, 5))
        for height in (0.0, 0.2, 0.3):
            with self.subTest(height=height), self.assertRaises(stockpiles.StockpileRejected) as caught:
                self.cut(self.terrain(((0, 19), (0, 19), height)), mark)
            self.assertEqual(caught.exception.message.code, NO_CELLS)
            self.assertEqual(dict(caught.exception.message.values), {"threshold": THRESHOLD_M})
        far = self.terrain(((10, 15), (10, 15), 2.0))
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            self.cut(far, mark)
        self.assertEqual(caught.exception.message.code, NO_CELLS)
        self.assertTrue(self.cut(self.terrain(((0, 19), (0, 19), 0.31)), mark).mask.all())

    def test_a_footprint_that_reaches_the_edge_of_the_enlarged_mark_is_noted(self) -> None:
        """RF-016-05: una zona que llena la marca ampliada (8 × 8) llega a su borde: la nota da el lugar de la primera
        celda de ese borde en el orden de lectura; una huella que no la toca, no da nota."""
        mark = rect(self.SHAPE, (8, 11), (8, 11))
        enlarged = rect(self.SHAPE, (6, 13), (6, 13))
        found = self.cut(self.terrain(((0, 19), (0, 19), 1.0)), mark, enlarged)
        np.testing.assert_array_equal(found.mask, enlarged)
        x, y = where(self.grid, 6, 6)
        self.assertEqual(values_of(found.notes, AT_EDGE), {"x": x, "y": y})
        inside = self.cut(self.terrain(((7, 12), (7, 12), 1.0)), mark, enlarged)
        self.assertEqual(inside.notes, ())

    def test_a_filled_hole_outside_the_enlarged_mark_is_not_its_edge(self) -> None:
        """RF-016-05: una marca ampliada con un bache (dos celdas de dentro que no son suyas) cuya zona lo rodea: el bache
        se rellena con la huella y no es el borde de la marca ampliada, así que las celdas que lo tocan no avisan."""
        enlarged = rect(self.SHAPE, (6, 13), (6, 13))
        enlarged[9:11, 9:11] = False
        found = self.cut(self.terrain(((7, 12), (7, 12), 1.0)), rect(self.SHAPE, (8, 8), (8, 8)), enlarged)
        np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (7, 12), (7, 12)))
        self.assertTrue(found.mask[9:11, 9:11].all())
        self.assertEqual(found.notes, ())

    def test_the_edge_of_the_window_is_the_edge_of_the_enlarged_mark(self) -> None:
        """Una marca ampliada que sale de la ventana queda cortada por ella: la huella que llega al borde de la
        ventana llega al de la marca ampliada."""
        found = self.cut(self.terrain(((0, 5), (0, 5), 1.0)), rect(self.SHAPE, (1, 2), (1, 2)))
        x, y = where(self.grid, 0, 0)
        self.assertEqual(values_of(found.notes, AT_EDGE), {"x": x, "y": y})

    def test_the_notes_come_in_the_order_edge_then_zones(self) -> None:
        z = self.terrain(((4, 13), (4, 13), 1.0), ((16, 19), (16, 19), 1.0))
        mark = np.zeros(self.SHAPE, dtype=bool)
        mark[8, 8] = mark[17, 17] = True
        found = self.cut(z, mark, rect(self.SHAPE, (4, 19), (4, 19)))
        self.assertEqual(codes_of(found.notes), [AT_EDGE, SEVERAL])

    def test_a_base_of_its_own_is_a_surface_not_a_plane(self) -> None:
        """RF-016-03: la base puede ser cualquier superficie (un levantamiento anterior): la huella son las celdas
        con ``z − base`` sobre el umbral, y donde la base no tiene dato falta terreno."""
        base = np.full(self.SHAPE, 5.0)
        base[3:8, 3:8] = 4.0
        z = np.full(self.SHAPE, 5.0)  # 1 m sobre la base donde esta es de 4 m
        found = self.cut(z, rect(self.SHAPE, (4, 4), (4, 4)), base=base)
        np.testing.assert_array_equal(found.mask, rect(self.SHAPE, (3, 7), (3, 7)))
        base[5, 5] = np.nan
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            self.cut(z, rect(self.SHAPE, (4, 4), (4, 4)), base=base)
        self.assertEqual(caught.exception.message.code, NO_TERRAIN)

    def test_nan_is_never_above_the_threshold_and_inputs_are_kept(self) -> None:
        """Una celda sin dato no está por encima de nada; ninguna entrada se modifica; las formas y los tipos se
        comprueban."""
        z = self.terrain(((3, 12), (3, 12), 1.0))
        z[3, 3] = np.nan
        mark = rect(self.SHAPE, (5, 5), (5, 5))
        snapshot = (z.copy(), self.base.copy(), mark.copy(), self.everywhere.copy())
        found = self.cut(z, mark)
        self.assertFalse(found.mask[3, 3])
        for after, before in zip((z, self.base, mark, self.everywhere), snapshot, strict=True):
            np.testing.assert_array_equal(after, before)
        for bad in (dict(z=z[:5]), dict(mark=mark.astype(np.int8)), dict(enlarged=self.everywhere[:, :5])):
            with self.subTest(bad=list(bad)), self.assertRaises(ValueError):
                stockpiles.footprint_above(bad.get("z", z), self.base, bad.get("mark", mark),
                                           bad.get("enlarged", self.everywhere), self.grid, THRESHOLD_M)
        for threshold in (math.nan, -0.1, math.inf):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                self.cut(z, mark, threshold_m=threshold)


class GrowTest(unittest.TestCase):
    """:func:`stockpiles.grow_footprint`: A2 y A3 en vueltas, con el volumen (CE-016-02, RF-016-02)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cone = sdata.mound_case("cone", 3.0)
        cls.pyramid = sdata.mound_case("pyramid", 3.0)

    def mark_of(self, case: object) -> np.ndarray:
        return sdata.in_box(case.mark_box, case.grid)

    def hand_base(self, grown: object, grid: object) -> list[list[float]]:
        """El plano del acopio evaluado celda a celda con el escalar ``BasePlane.at``, no con ``values``."""
        x, y = grid.centers()
        return [[float(grown.plane.at(float(x[r, c]), float(y[r, c]))) for c in range(grid.ncols)]
                for r in range(grid.nrows)]

    def test_the_cone_has_the_footprint_the_plane_and_the_volume_by_hand(self) -> None:
        """CE-016-02, RF-016-02: el cono sobre el plano de 3° con sus ocho atípicas: la huella son las celdas de más
        de 0,3 m sobre el plano sintético (las del cono, sin las atípicas, que no tocan la marca o son otra zona), el
        plano se recupera a ≤ 10⁻⁶ m y el volumen es el cálculo a mano sobre las mismas celdas y el mismo plano, y el
        del cono (la suma de sus alturas en esas celdas), a ≤ 10⁻⁹ relativo; converge en la segunda vuelta."""
        case = self.cone
        grown = stockpiles.grow_footprint(case.terrain, self.mark_of(case), case.grid, params_of())
        analytic = case.height > THRESHOLD_M
        np.testing.assert_array_equal(grown.mask, analytic)
        self.assertLess(float(np.abs(grown.base - case.base)[analytic].max()), 1e-6)
        self.assertLess(float(np.abs(grown.plane.values(case.grid) - case.base).max()), 1e-6)
        self.assertEqual((grown.turns, grown.converged), (2, True))
        by_hand = oracles.hand_volume(case.terrain.tolist(), self.hand_base(grown, case.grid), grown.mask.tolist(),
                                      1.0, THRESHOLD_M)
        self.assertAlmostEqual(grown.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9)
        cone = math.fsum(case.height[analytic].ravel().tolist())
        self.assertAlmostEqual(grown.volume_m3 / cone - 1.0, 0.0, delta=1e-9)
        self.assertEqual(grown.area_m2, float(analytic.sum()))

    def test_the_outliers_inside_the_mark_are_other_zones(self) -> None:
        """RF-016-05: de las ocho atípicas, solo las positivas que caen dentro de la marca forman otra zona que la toca
        (dos); la nota dice 3 zonas y el lugar de la primera de las otras en el orden de lectura; las demás (fuera de la
        marca o negativas) no son zona de la marca."""
        case = self.cone
        grown = stockpiles.grow_footprint(case.terrain, self.mark_of(case), case.grid, params_of())
        inside = case.outliers & self.mark_of(case) & (case.offsets > THRESHOLD_M)
        self.assertEqual(int(inside.sum()), 2)
        values = values_of(grown.notes, SEVERAL)
        self.assertEqual(values["zones"], 3)
        row, col = np.argwhere(inside)[0]
        x, y = where(case.grid, int(row), int(col))
        self.assertEqual((values["x"], values["y"]), (x, y))
        self.assertEqual(codes_of(grown.notes), [SEVERAL])

    def test_the_pyramid_has_its_footprint_and_the_volume_of_its_own_plane(self) -> None:
        """RF-016-02: con la pirámide la huella son sus 1.444 celdas y el volumen, el cálculo a mano sobre las mismas
        celdas y el mismo plano a ≤ 10⁻⁹ relativo (el plano converge a unos 4,5 mm del sintético: cuatro celdas de las
        esquinas de la corona son del propio montón, como anotó la T06; por eso el analítico, solo al 0,5 %)."""
        case = self.pyramid
        grown = stockpiles.grow_footprint(case.terrain, self.mark_of(case), case.grid, params_of())
        analytic = case.height > THRESHOLD_M
        self.assertEqual(int(analytic.sum()), 1444)
        np.testing.assert_array_equal(grown.mask, analytic)
        by_hand = oracles.hand_volume(case.terrain.tolist(), self.hand_base(grown, case.grid), grown.mask.tolist(),
                                      1.0, THRESHOLD_M)
        self.assertAlmostEqual(grown.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9)
        self.assertAlmostEqual(grown.volume_m3 / math.fsum(case.height[analytic].ravel().tolist()) - 1.0, 0.0,
                               delta=5e-3)

    def test_cells_of_two_metres_count_four_square_metres_each(self) -> None:
        """RF-016-02: con celdas de 2 m el área de cada una es de 4 m²: el cono de CE-016-02 tiene la huella analítica,
        el área son sus celdas por 4 y el volumen, la suma de sus alturas por 4, a ≤ 10⁻⁹ relativo."""
        case = sdata.mound_case("cone", 3.0, step_m=2.0)
        grown = stockpiles.grow_footprint(case.terrain, self.mark_of(case), case.grid, params_of())
        analytic = case.height > THRESHOLD_M
        np.testing.assert_array_equal(grown.mask, analytic)
        self.assertEqual(grown.area_m2, 4.0 * float(analytic.sum()))
        self.assertAlmostEqual(grown.volume_m3 / (4.0 * math.fsum(case.height[analytic].tolist())) - 1.0, 0.0,
                               delta=1e-9)
        self.assertEqual(stockpiles.footprint_volume(np.full((3, 3), 2.0), np.zeros((3, 3)), np.ones((3, 3), bool),
                                                     4.0, THRESHOLD_M), 72.0)

    def test_the_plane_of_a_converged_footprint_is_the_plane_of_that_footprint(self) -> None:
        """RF-016-02: «repitiendo A2 con la huella nueva hasta que no cambie»: al converger, el plano es el de A2 sobre
        la huella final (no sobre la marca), y la huella de ese plano es la misma huella."""
        case = self.cone
        mark = self.mark_of(case)
        grown = stockpiles.grow_footprint(case.terrain, mark, case.grid, params_of())
        again = stockpiles.base_plane(case.terrain, grown.mask, case.grid, params_of().plane)
        np.testing.assert_array_equal(grown.base, again.values(case.grid))
        cut = stockpiles.footprint_above(case.terrain, grown.base, mark,
                                         morphology.dilate(mark, MARGIN_M, 1.0), case.grid, THRESHOLD_M)
        np.testing.assert_array_equal(cut.mask, grown.mask)

    def test_the_small_cones_and_pyramids_are_the_independent_hand_calculation(self) -> None:
        """RF-016-02, RF-016-05, RF-016-07: A2 y A3 enteros contra el oráculo (bucles de Python: la corona por fuerza
        bruta, las celdas llanas, el plano en racionales exactos, la huella por una búsqueda en anchura): la misma
        huella, el mismo plano (≤ 10⁻⁹ relativo en cada celda), el mismo volumen, las mismas vueltas y las mismas notas,
        con un cono, una pirámide, las celdas atípicas, un plano limitado a 4° (el de 8°) y un cráter."""
        cases = {"cono": small_scene("cone"), "pirámide con atípicas": small_scene("pyramid", blocks=SPIKES),
                 "cono a 8°": small_scene("cone", 8.0), "cono con cráter": small_scene("cone", flatten=(
                     (13.0, 13.0, 17.0, 17.0),))}
        for name, scene in cases.items():
            with self.subTest(name):
                grown = stockpiles.grow_footprint(scene.terrain, scene.mark, scene.grid, params_of(margin_m=3.0))
                hand = hand_grow(scene.terrain, scene.grid, scene.mark, margin_m=3.0)
                np.testing.assert_array_equal(grown.mask, hand.found.mask)
                np.testing.assert_allclose(grown.base, hand.base, rtol=1e-9, atol=0.0)
                self.assertAlmostEqual(grown.volume_m3 / hand.volume - 1.0, 0.0, delta=1e-9)
                self.assertEqual((grown.turns, grown.converged), (hand.turns, hand.converged))
                self.assertEqual(codes_of(grown.notes), expected_codes(hand))
                self.assertEqual(grown.plane.limited, hand.plane.limited)

    def test_a_small_cone_has_the_volume_of_its_heights_less_the_crater(self) -> None:
        """D-18: el cono pequeño (pie de 6 m, cima de 2 m, 2 m de altura) tiene la huella de las celdas a menos de 5,4
        m del centro; su volumen es la suma de sus alturas (a mano con ``fsum``). Con un cráter de 4 × 4 celdas al
        nivel del plano la huella lo rellena (el área no cambia) y el volumen pierde exactamente lo que había en él
        (31,757… m³, contado a mano)."""
        full = small_scene("cone")
        crater_box = (13.0, 13.0, 17.0, 17.0)
        crater = small_scene("cone", flatten=(crater_box,))
        analytic = full.height > THRESHOLD_M
        whole = stockpiles.grow_footprint(full.terrain, full.mark, full.grid, params_of(margin_m=3.0))
        holed = stockpiles.grow_footprint(crater.terrain, crater.mark, crater.grid, params_of(margin_m=3.0))
        self.assertEqual(int(whole.mask.sum()), int(analytic.sum()))
        np.testing.assert_array_equal(holed.mask, whole.mask)
        self.assertEqual(holed.area_m2, whole.area_m2)
        self.assertAlmostEqual(whole.volume_m3 / math.fsum(full.height[analytic].tolist()) - 1.0, 0.0, delta=1e-9)
        removed = full.height[sdata.in_box(crater_box, full.grid)]
        self.assertAlmostEqual((whole.volume_m3 - holed.volume_m3) / math.fsum(removed.tolist()) - 1.0, 0.0,
                               delta=1e-9)
        # a mano: las 4 celdas del centro (a 0,71 m) y las 8 de al lado (a 1,58 m) están en la cima de 2 m (hasta 2 m
        # del centro, la altura es 2 m) y las 4 esquinas (a 2,12 m) tienen 0,5·(6 − 1,5·√2)
        self.assertAlmostEqual(float(removed.sum()), 12 * 2.0 + 4 * 0.5 * (6.0 - 1.5 * math.sqrt(2.0)), delta=1e-12)

    def test_a_footprint_clipped_by_the_enlarged_mark_is_noted_where_it_reaches_it(self) -> None:
        """RF-016-05: una lengua de 3 m que sale del montón y cruza la corona hasta el borde de la ventana llena la marca
        ampliada: nota de que llega a su borde, con el lugar que ve el oráculo (la primera celda de ese borde en el orden
        de lectura), igual que la huella y el plano a mano."""
        scene = small_scene("pyramid", blocks=(((19.0, 13.0, 30.0, 17.0), 3.0),))
        grown = stockpiles.grow_footprint(scene.terrain, scene.mark, scene.grid, params_of(margin_m=3.0))
        hand = hand_grow(scene.terrain, scene.grid, scene.mark, margin_m=3.0)
        np.testing.assert_array_equal(grown.mask, hand.found.mask)
        self.assertIsNotNone(hand.found.first_edge)
        x, y = where(scene.grid, *hand.found.first_edge)
        self.assertEqual(values_of(grown.notes, AT_EDGE), {"x": x, "y": y})
        np.testing.assert_allclose(grown.base, hand.base, rtol=1e-9, atol=0.0)

    def test_it_does_not_settle_in_one_turn_and_says_so_where_it_moved(self) -> None:
        """RF-016-05: con una sola vuelta la huella (la del montón) no es la de la marca, así que no se sabe si es
        estable: nota de que no se estabiliza con las vueltas y el centro de las celdas que cambiaron (la marca
        menos la huella, a mano); se queda con el último plano y la última huella, iguales al oráculo de una vuelta. Con
        dos vueltas, converge y no avisa."""
        scene = small_scene("pyramid")
        scene = Scene(scene.grid, scene.base, scene.height, scene.terrain,  # una marca desplazada 3 m al este
                      sdata.in_box((10.0, 7.0, 26.0, 23.0), scene.grid))
        grown = stockpiles.grow_footprint(scene.terrain, scene.mark, scene.grid, params_of(margin_m=3.0, turns=1))
        hand = hand_grow(scene.terrain, scene.grid, scene.mark, margin_m=3.0, turns=1)
        self.assertEqual((grown.turns, grown.converged, hand.converged), (1, False, False))
        np.testing.assert_array_equal(grown.mask, hand.found.mask)
        np.testing.assert_allclose(grown.base, hand.base, rtol=1e-9, atol=0.0)
        values = values_of(grown.notes, NOT_CONVERGED)
        moved = np.argwhere(hand.found.mask ^ scene.mark)
        x, y = centre(scene.grid, [tuple(cell) for cell in moved])
        self.assertEqual(values["turns"], 1)
        self.assertAlmostEqual(values["x"], x, delta=1e-6)
        self.assertAlmostEqual(values["y"], y, delta=1e-6)
        footprint_x, _ = centre(scene.grid, [tuple(cell) for cell in np.argwhere(hand.found.mask)])
        self.assertGreater(x - footprint_x, 1.0, "no es el centro de la huella: las celdas que cambiaron están al este")
        self.assertEqual(codes_of(grown.notes)[-1], NOT_CONVERGED)
        settled = stockpiles.grow_footprint(scene.terrain, scene.mark, scene.grid, params_of(margin_m=3.0, turns=2))
        self.assertEqual((settled.turns, settled.converged), (2, True))
        self.assertNotIn(NOT_CONVERGED, codes_of(settled.notes))

    def test_the_notes_of_the_plane_come_between_the_footprint_ones_and_the_unsettled_one(self) -> None:
        """El orden de las notas de un acopio: llega al borde, más de una zona, corona poco llana, plano limitado y no
        se estabiliza."""
        scene = small_scene("cone", 8.0, blocks=(SPIKES[1],))
        grown = stockpiles.grow_footprint(scene.terrain, scene.mark, scene.grid, params_of(margin_m=3.0, turns=1))
        hand = hand_grow(scene.terrain, scene.grid, scene.mark, margin_m=3.0, turns=1)
        self.assertTrue(grown.plane.limited)
        self.assertEqual(codes_of(grown.notes), expected_codes(hand))
        order = [AT_EDGE, SEVERAL, FEW_FLAT, TILT, NOT_CONVERGED]
        self.assertEqual(codes_of(grown.notes), [code for code in order if code in codes_of(grown.notes)])
        self.assertIn(TILT, codes_of(grown.notes))
        self.assertIn(NOT_CONVERGED, codes_of(grown.notes))

    def test_a_mound_that_is_not_there_and_missing_terrain_reject_the_stockpile(self) -> None:
        """RF-016-04: una marca sin acopio (nada sobre el umbral) o con terreno que falta en la corona se rechaza,
        con el caso de A2 o el de A3; el rechazo no se registra ni para a las demás."""
        scene = small_scene("cone")
        empty = scene.base.copy()
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            stockpiles.grow_footprint(empty, scene.mark, scene.grid, params_of(margin_m=3.0))
        self.assertEqual(caught.exception.message.code, NO_CELLS)
        holed = scene.terrain.copy()
        holed[sdata.in_box((24.0, 14.0, 26.0, 16.0), scene.grid)] = np.nan
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            stockpiles.grow_footprint(holed, scene.mark, scene.grid, params_of(margin_m=3.0))
        self.assertEqual(caught.exception.message.code, "des.stockpile_no_terrain_crown")
        interior = scene.terrain.copy()
        interior[14:17, 14:17] = np.nan
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            stockpiles.grow_footprint(interior, scene.mark, scene.grid, params_of(margin_m=3.0))
        self.assertEqual(caught.exception.message.code, NO_TERRAIN)
        self.assertEqual(dict(caught.exception.message.values)["cells"], 9)

    def test_a_zero_margin_keeps_the_footprint_inside_the_mark(self) -> None:
        """Con margen 0 la marca ampliada es la marca: una marca más pequeña que el montón lo corta y avisa de que
        llega a su borde."""
        scene = small_scene("cone")
        mark = sdata.in_box((11.0, 11.0, 19.0, 19.0), scene.grid)
        grown = stockpiles.grow_footprint(scene.terrain, mark, scene.grid, params_of(margin_m=0.0))
        self.assertTrue(((grown.mask & ~mark).sum() == 0))
        self.assertIn(AT_EDGE, codes_of(grown.notes))

    def test_inputs_are_not_modified_and_one_mark_is_far_below_the_step_budget(self) -> None:
        """Principio 7: ni la superficie ni la marca cambian. RNF-016-03 y plan §7.3 (3 ms por marca): el cono de la
        ventana de los casos (120 × 120 celdas) entero cabe en un paso (< 0,2 s por llamada)."""
        case = self.cone
        z, mark = case.terrain.copy(), self.mark_of(case)
        snapshot = mark.copy()
        stockpiles.grow_footprint(z, mark, case.grid, params_of())
        np.testing.assert_array_equal(z, case.terrain)
        np.testing.assert_array_equal(mark, snapshot)
        started = time.perf_counter()
        stockpiles.grow_footprint(z, mark, case.grid, params_of())
        self.assertLess(time.perf_counter() - started, 0.2)


class ParamsTest(unittest.TestCase):
    """Los umbrales de A3 se comprueban con los límites de ``design.params`` (la única fuente)."""

    def test_valid_parameters_are_kept_as_given(self) -> None:
        found = params_of(margin_m=0.0, turns=1, threshold_m=0.0)
        self.assertEqual((found.margin_m, found.turns, found.threshold_m), (0.0, 1, 0.0))
        self.assertIsInstance(found.plane, stockpiles.PlaneParams)

    def test_out_of_range_values_are_refused_naming_the_parameter(self) -> None:
        for name, value in (("margin_m", -1.0), ("margin_m", math.nan), ("turns", 0), ("turns", 101),
                            ("turns", 2.5), ("threshold_m", -0.01), ("threshold_m", math.nan),
                            ("threshold_m", math.inf)):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError) as caught:
                params_of(**{name: value})
            self.assertIn(name, str(caught.exception))

    def test_grow_needs_square_cells_a_matching_window_and_footprint_params(self) -> None:
        scene = small_scene("cone")
        with self.assertRaises(TypeError):
            stockpiles.grow_footprint(scene.terrain, scene.mark, scene.grid, stockpiles.PlaneParams(**D3))
        with self.assertRaises(ValueError):
            stockpiles.grow_footprint(scene.terrain[:10], scene.mark, scene.grid, params_of())
        with self.assertRaises(ValueError):
            stockpiles.grow_footprint(scene.terrain, scene.mark[:10], scene.grid, params_of())
        with self.assertRaises(ValueError):
            stockpiles.grow_footprint(scene.terrain, scene.mark, gis.Grid(sdata.BASE[0], sdata.BASE[1] + 60.0, 1.0, 2.0, 30, 30),
                                      params_of())


class ShareRuleTest(unittest.TestCase):
    """El reparto de las celdas comunes (RF-016-06, D-16) con casos de una fila contados a mano."""

    SHAPE = (1, 15)

    def setUp(self) -> None:
        self.grid = gis.Grid(sdata.BASE[0], sdata.BASE[1] + 1.0, 1.0, 1.0, 15, 1)
        self.z = np.full(self.SHAPE, 1.0)

    def claims(self, *specs: tuple[str, tuple[int, int], tuple[int, int]]) -> list[object]:
        """Una reclamación por ``(nombre, columnas de la marca, columnas de la huella)``, de una fila."""
        found = []
        for name, mark_cols, footprint_cols in specs:
            mask = rect(self.SHAPE, (0, 0), footprint_cols)
            footprint = stockpiles.Footprint(mask, np.zeros(self.SHAPE), None, 0.0, 0.0, 1, True, ())
            found.append(stockpiles.Claim(name, rect(self.SHAPE, (0, 0), mark_cols), footprint))
        return found

    def share(self, claims: list[object]) -> object:
        return stockpiles.share_cells(claims, self.z, self.grid, THRESHOLD_M)

    def test_a_cell_goes_to_the_mark_that_contains_it_else_to_the_nearest(self) -> None:
        """RF-016-06: las columnas 3 y 4 (de la marca A) a A, la 6 y la 7 (de la B) a B; la 5, en el hueco entre las
        dos marcas, a igual distancia de las dos (1 celda): a la primera de la lista; con el orden cambiado, a la otra."""
        claims = self.claims(("A", (0, 4), (0, 7)), ("B", (6, 10), (3, 10)))
        done = self.share(claims)
        np.testing.assert_array_equal(done.footprints[0].mask, rect(self.SHAPE, (0, 0), (0, 5)))
        np.testing.assert_array_equal(done.footprints[1].mask, rect(self.SHAPE, (0, 0), (6, 10)))
        swapped = self.share(claims[::-1])
        np.testing.assert_array_equal(swapped.footprints[0].mask, rect(self.SHAPE, (0, 0), (5, 10)))
        np.testing.assert_array_equal(swapped.footprints[1].mask, rect(self.SHAPE, (0, 0), (0, 4)))

    def test_without_a_containing_mark_the_nearest_wins_by_the_exact_distance(self) -> None:
        """Las huellas se solapan en las columnas 4 a 6 y ninguna marca las contiene (A, columnas 0 a 1; B, 9 a 10):
        las más próximas a A (la 4: 3 celdas contra 5) son de A, la 5 (4 contra 4) empata y es de A, la 6 (5 contra
        3), de B."""
        done = self.share(self.claims(("A", (0, 1), (0, 6)), ("B", (9, 10), (4, 10))))
        np.testing.assert_array_equal(done.footprints[0].mask, rect(self.SHAPE, (0, 0), (0, 5)))
        np.testing.assert_array_equal(done.footprints[1].mask, rect(self.SHAPE, (0, 0), (6, 10)))

    def test_a_cell_both_marks_contain_goes_to_the_nearest_so_to_the_first_on_a_tie(self) -> None:
        """Si la contienen las dos (marcas solapadas, que T11 rechaza, pero la regla las trata) la distancia a las dos
        es 0 y gana la primera de la lista: las columnas 4 y 5 son de las dos marcas y van a A; la 6, solo de B, a B."""
        done = self.share(self.claims(("A", (0, 5), (0, 6)), ("B", (4, 10), (4, 10))))
        np.testing.assert_array_equal(done.footprints[0].mask, rect(self.SHAPE, (0, 0), (0, 5)))
        np.testing.assert_array_equal(done.footprints[1].mask, rect(self.SHAPE, (0, 0), (6, 10)))

    def test_only_the_claimants_count_as_containing(self) -> None:
        """Una tercera marca C que contiene las celdas comunes de A y B (4 a 6) pero no las reclama (su huella, 9 a 13,
        solo toca la de B) no cuenta para ellas: se reparten entre A (marca 0 a 2) y B (marca 8 a 10) por la distancia:
        la 4 (2 contra 4 celdas) a A, la 5 (3 contra 3, un empate) a la primera, A, y la 6 (4 contra 2) a B; y las 9 y
        10, que B y C se disputan, son de B, que las contiene (C está a 3 celdas)."""
        claims = self.claims(("A", (0, 2), (0, 6)), ("B", (8, 10), (4, 10)), ("C", (4, 6), (9, 13)))
        done = self.share(claims)
        np.testing.assert_array_equal(done.footprints[0].mask, rect(self.SHAPE, (0, 0), (0, 5)))
        np.testing.assert_array_equal(done.footprints[1].mask, rect(self.SHAPE, (0, 0), (6, 10)))
        np.testing.assert_array_equal(done.footprints[2].mask, rect(self.SHAPE, (0, 0), (11, 13)))
        self.assertEqual([(pair.mark, pair.other, pair.cells) for pair in done.shared], [("A", "B", 3), ("B", "C", 2)])

    def test_the_winner_keeps_its_footprint_as_it_was(self) -> None:
        """Una huella que se queda con todas las celdas comunes (la marca A las contiene) no cambia: es el mismo objeto;
        la otra, sí, y pierde justo lo que se repartió."""
        claims = self.claims(("A", (0, 5), (0, 6)), ("B", (9, 10), (4, 10)))
        done = self.share(claims)
        self.assertIs(done.footprints[0], claims[0].footprint)
        self.assertIsNot(done.footprints[1], claims[1].footprint)
        np.testing.assert_array_equal(done.footprints[1].mask, rect(self.SHAPE, (0, 0), (7, 10)))

    def test_three_footprints_agree_with_the_hand_share(self) -> None:
        """Tres huellas que se tocan por parejas: el reparto es el del oráculo y las parejas se avisan una a una."""
        claims = self.claims(("A", (0, 2), (0, 5)), ("B", (4, 6), (3, 8)), ("C", (8, 10), (6, 10)))
        done = self.share(claims)
        expected = oracles.hand_share([c.footprint.mask.tolist() for c in claims], [c.mark.tolist() for c in claims])
        for found, mask in zip(done.footprints, expected, strict=True):
            np.testing.assert_array_equal(found.mask, mask)
        self.assertEqual([(pair.mark, pair.other, pair.cells) for pair in done.shared],
                         [("A", "B", 3), ("B", "C", 3)])
        union = np.logical_or.reduce([c.footprint.mask for c in claims])
        np.testing.assert_array_equal(np.logical_or.reduce([f.mask for f in done.footprints]), union)
        self.assertEqual(sum(int(f.mask.sum()) for f in done.footprints), int(union.sum()))

    def test_no_shared_cell_leaves_everything_as_it_was(self) -> None:
        claims = self.claims(("A", (0, 3), (0, 4)), ("B", (6, 10), (5, 10)))
        done = self.share(claims)
        self.assertEqual(done.shared, ())
        for before, after in zip(claims, done.footprints, strict=True):
            self.assertIs(after, before.footprint)

    def test_the_record_has_the_two_marks_the_area_and_where(self) -> None:
        """RF-016-06: el aviso nombra las dos marcas, el área repartida (m²) y el lugar (el centro de las celdas
        comunes); su texto en español los dice."""
        done = self.share(self.claims(("A", (0, 4), (0, 7)), ("B", (6, 10), (3, 10))))
        (pair,) = done.shared
        self.assertEqual((pair.mark, pair.other, pair.cells, pair.area_m2), ("A", "B", 5, 5.0))
        x, y = centre(self.grid, [(0, col) for col in range(3, 8)])
        self.assertAlmostEqual(pair.x, x, delta=1e-6)
        self.assertAlmostEqual(pair.y, y, delta=1e-6)
        text = pair.message.notice("A", 0.0, 0.0).text("es")
        self.assertIn("«A»", text)
        self.assertIn("«B»", text)
        self.assertIn("5", text)
        self.assertEqual(pair.message.code, SHARED)

    def test_with_cells_of_two_metres_the_areas_are_in_square_metres(self) -> None:
        """RF-016-06: con celdas de 2 m, cada celda común son 4 m²: el área repartida, el área y el volumen de cada
        huella (a 1 m de altura sobre su base, a mano: 6 celdas para A y 5 para B) y el centro de las celdas comunes
        (columnas 3 a 7, de 2 m) son los del cálculo a mano."""
        grid = gis.Grid(sdata.BASE[0], sdata.BASE[1] + 2.0, 2.0, 2.0, 15, 1)
        done = stockpiles.share_cells(self.claims(("A", (0, 4), (0, 7)), ("B", (6, 10), (3, 10))), self.z, grid,
                                      THRESHOLD_M)
        (pair,) = done.shared
        self.assertEqual((pair.cells, pair.area_m2), (5, 20.0))
        self.assertAlmostEqual(pair.x, sdata.BASE[0] + 2.0 * (5.0 + 0.5), delta=1e-9)  # el centro de las columnas 3 a 7
        first, second = done.footprints
        self.assertEqual((first.area_m2, first.volume_m3), (24.0, 24.0))
        self.assertEqual((second.area_m2, second.volume_m3), (20.0, 20.0))

    def test_duplicated_names_and_mismatched_masks_are_refused(self) -> None:
        claims = self.claims(("A", (0, 2), (0, 5)), ("A", (6, 8), (4, 8)))
        with self.assertRaises(ValueError):
            self.share(claims)
        short = stockpiles.Claim("B", rect((1, 5), (0, 0), (0, 2)), claims[0].footprint)
        with self.assertRaises(ValueError):
            self.share([claims[0], short])
        with self.assertRaises(ValueError):
            self.share([])


class TouchingPairTest(unittest.TestCase):
    """E1, RF-016-06: los dos acopios que se tocan de la cantera (Acopio 1 y 2, pirámides de 4 m de altura a 20 m una
    de otra, con los pies solapados 4 m) sobre un plano de 3°."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = sdata.touching_pair()
        cls.marks = [sdata.in_box(mark.box, cls.case.grid) for mark in cls.case.marks]
        cls.params = params_of()
        cls.grown = [stockpiles.grow_footprint(cls.case.terrain, mark, cls.case.grid, cls.params)
                     for mark in cls.marks]
        cls.claims = [stockpiles.Claim(mark.name, mask, grown)
                      for mark, mask, grown in zip(cls.case.marks, cls.marks, cls.grown, strict=True)]
        cls.shared = stockpiles.share_cells(cls.claims, cls.case.terrain, cls.case.grid, THRESHOLD_M)

    def test_the_two_footprints_share_cells_before_the_share(self) -> None:
        """Las marcas se tocan por el borde (ninguna celda común) y, aun así, las huellas, que se forman dentro de la
        marca ampliada por el margen, comparten celdas: los dos montones son una sola zona."""
        self.assertFalse((self.marks[0] & self.marks[1]).any())
        common = self.grown[0].mask & self.grown[1].mask
        self.assertGreater(int(common.sum()), 96, "las huellas comparten más que los pies de los montones")

    def test_after_the_share_the_footprints_are_disjoint_and_cover_the_same_cells(self) -> None:
        """RF-016-06: cada celda común queda en una sola huella y la unión no cambia."""
        first, second = (found.mask for found in self.shared.footprints)
        self.assertFalse((first & second).any())
        np.testing.assert_array_equal(first | second, self.grown[0].mask | self.grown[1].mask)

    def test_the_share_is_the_hand_share(self) -> None:
        """RF-016-06: cada celda común, a la marca que la contiene o, si ninguna la contiene, a la más próxima por la
        distancia exacta: igual que el oráculo de fuerza bruta."""
        expected = oracles.hand_share([found.mask.tolist() for found in self.grown],
                                      [mark.tolist() for mark in self.marks])
        for found, mask in zip(self.shared.footprints, expected, strict=True):
            np.testing.assert_array_equal(found.mask, mask)
        common = self.grown[0].mask & self.grown[1].mask
        first, second = (found.mask for found in self.shared.footprints)
        self.assertTrue(first[common & self.marks[0]].all())
        self.assertTrue(second[common & self.marks[1]].all())
        # a mano: las dos marcas son iguales y se tocan en x = 60 m (local), así que la recta que las reparte es esa y
        # cada celda común va a la marca de su lado, también las que quedan fuera de las dos por el norte o el sur
        x, _ = sdata.local_centers(self.case.grid)
        np.testing.assert_array_equal(first[common], x[common] < 60.0)
        np.testing.assert_array_equal(second[common], x[common] > 60.0)

    def test_the_notice_names_both_marks_and_the_area_shared(self) -> None:
        """RF-016-06: un aviso con las dos marcas y el área de las celdas comunes antes del reparto."""
        (pair,) = self.shared.shared
        common = self.grown[0].mask & self.grown[1].mask
        self.assertEqual((pair.mark, pair.other), ("Acopio 1", "Acopio 2"))
        self.assertEqual((pair.cells, pair.area_m2), (int(common.sum()), float(common.sum())))
        x, y = centre(self.case.grid, [tuple(cell) for cell in np.argwhere(common)])
        self.assertAlmostEqual(pair.x, x, delta=1e-6)
        self.assertAlmostEqual(pair.y, y, delta=1e-6)
        self.assertAlmostEqual(pair.x, sdata.BASE[0] + 60.0, delta=1e-6)  # por simetría, el centro de las dos
        self.assertAlmostEqual(pair.y, sdata.BASE[1] + 60.0, delta=1e-6)

    def test_the_volume_is_measured_on_the_cells_each_one_keeps(self) -> None:
        """RF-016-02, RF-016-06: el volumen de cada acopio se recalcula sobre la huella que le queda, con su plano, y es
        el cálculo a mano a ≤ 10⁻⁹ relativo; no se cuenta dos veces nada: la suma es lo de la unión de los dos montones
        sobre el plano sintético (2.178 m³ en total y 2.145 m³ en las celdas que pasan de 0,3 m: la suma sale
        2.143 m³, a 0,1 %: los planos de cada uno están a 1,6 cm del sintético por la pendiente del otro montón)."""
        total = []
        for found, claim in zip(self.shared.footprints, self.claims, strict=True):
            base = claim.footprint.base.tolist()
            by_hand = oracles.hand_volume(self.case.terrain.tolist(), base, found.mask.tolist(), 1.0, THRESHOLD_M)
            self.assertAlmostEqual(found.volume_m3 / by_hand - 1.0, 0.0, delta=1e-9)
            self.assertEqual(found.area_m2, float(found.mask.sum()))
            total.append(found.volume_m3)
        union = self.case.height > THRESHOLD_M
        self.assertAlmostEqual(math.fsum(total) / math.fsum(self.case.height[union].tolist()) - 1.0, 0.0, delta=2e-3)

    def test_a_footprint_not_touched_by_the_share_is_the_same_object(self) -> None:
        """Una huella sin celdas comunes no se recalcula: es el mismo objeto."""
        box = sdata.in_box((100.0, 100.0, 110.0, 110.0), self.case.grid)
        alone = stockpiles.Footprint(box, self.grown[0].base, None, 0.0, 100.0, 1, True, ())
        done = stockpiles.share_cells([*self.claims, stockpiles.Claim("Lejos", box, alone)], self.case.terrain,
                                      self.case.grid, THRESHOLD_M)
        self.assertIs(done.footprints[2], alone)
        self.assertEqual(len(done.shared), 1)


class ShareStepsTest(unittest.TestCase):
    """La variante por pasos: el mismo resultado, en pasos pequeños y sin dejar nada a mitad."""

    @classmethod
    def setUpClass(cls) -> None:
        pair = TouchingPairTest
        pair.setUpClass()
        cls.case, cls.claims = pair.case, pair.claims

    def test_the_steps_give_the_same_share_in_small_steps(self) -> None:
        """RNF-016-03: el último paso lleva el resultado, igual que el de una pieza, y ninguna llamada pasa de 0,05 s."""
        whole = stockpiles.share_cells(self.claims, self.case.terrain, self.case.grid, THRESHOLD_M)
        steps = stockpiles.share_cells_steps(self.claims, self.case.terrain, self.case.grid, THRESHOLD_M,
                                             budget_s=0.0)
        longest, count = 0.0, 0
        last = None
        with closing(steps):
            while True:
                started = time.perf_counter()
                try:
                    last = next(steps)
                except StopIteration:
                    break
                longest, count = max(longest, time.perf_counter() - started), count + 1
        self.assertGreater(count, 1)
        self.assertLess(longest, 0.05)
        for found, expected in zip(last.result.footprints, whole.footprints, strict=True):
            np.testing.assert_array_equal(found.mask, expected.mask)
            self.assertEqual(found.volume_m3, expected.volume_m3)
        self.assertEqual(last.result.shared, whole.shared)

    def test_closing_halfway_leaves_the_inputs_as_they_were(self) -> None:
        before = [claim.footprint.mask.copy() for claim in self.claims]
        steps = stockpiles.share_cells_steps(self.claims, self.case.terrain, self.case.grid, THRESHOLD_M,
                                             budget_s=0.0)
        next(steps)
        steps.close()
        for claim, mask in zip(self.claims, before, strict=True):
            np.testing.assert_array_equal(claim.footprint.mask, mask)

    def test_refusals_come_in_the_call(self) -> None:
        with self.assertRaises(ValueError):
            stockpiles.share_cells_steps([], self.case.terrain, self.case.grid, THRESHOLD_M)


if __name__ == "__main__":
    unittest.main()
