# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del hito H2 de la cantera con dos superficies (spec 014, T24; HU-014-3,
HU-014-4; RF-014-12 a RF-014-18; CE-014-04 y CE-014-05; plan 014 A8, A9, §7.1).

**CE-014-04** (dos superficies): **100 diseños sintéticos**, cada uno con **los dos órdenes**, por
``design.quarry.quarry_steps`` (la regla de orden, ``≤ z``, el invariante de RF-014-14, la
clasificación, el aviso y las cifras). Cada diseño es una cantera en una rejilla de 26 × 30 celdas
de 2 m con su terreno (una ladera con relieve; en algunos, un hueco sin dato), un recinto (un
rectángulo con una zona sin corte a sostener), dos sectores (en algunos, con filas de ningún
sector), una zona de restauración por relleno (o ninguna) y su espesor mínimo; las dos superficies
salen de perfiles, anclas y métricas al azar:

- en los **20 primeros**, las calcula ``side_steps`` de verdad (coronación y zonas a sostener, a
  veces un fondo con el ancla «al fondo de cada muro»; la métrica *chamfer* 5×5, la única que
  admite la envolvente por sectores de la 013), una vez por diseño: los lados no dependen del orden
  (T16), así que ``quarry_steps`` de cada orden recibe esos mismos lados; en el primero se comprueba
  que es lo mismo que calcularlo todo otra vez;
- en los **80 restantes**, cada superficie es un escalonado de la 013 hecho con sus piezas
  (envolvente *chamfer* desde semillas al azar —la coronación, un fondo o cotas sueltas por debajo
  del terreno— y ``bench_cut``, compuesto con el recinto o, una de cada cinco, sin componer, por
  encima del terreno en parte): pares de superficies que se cruzan de todas las maneras, que el
  orden tiene que atar (y bajar a ``≤ z``).

En **todas las celdas** de los 200 resultados: ``final ≤ explotación ≤ terreno`` sin tolerancia
(y sin dato donde el terreno no lo tiene), la regla de RF-014-13 a mano bit a bit y, fuera del
recinto, el terreno; y los volúmenes de la clasificación (desdoblado, relleno de restauración y la
excavación de la explotación, con sus áreas, en total, por la zona de relleno y por sector) iguales
a los de **la cubicación de la 011** a ≤ 10⁻⁶ relativo: su núcleo (``reserves.kernel``) con los
pesos de sus polígonos (``reserves.polygons``) sobre las mismas rejillas (la prueba importa
``reserves``; ``design`` no). Que la cubicación entera, con sus GeoTIFF, da lo mismo que su núcleo
lo comprueban la T17 (en la cantera) y la historia de Blender del hito.

**CE-014-05** (regresión del error 60): sobre la rejilla, el recinto y los sectores de la cantera de
``tests.support.quarry_fixtures`` (400 × 400 celdas de 1 m) con el terreno **llano** a 234,25 m (una
meseta, para que la cuenta a mano sea exacta), la explotación excavada a 225 m en el recinto y la
final igual a ella, salvo en dos zonas **sin explotar** (la explotación es el terreno) con la final
10 m por debajo (224,25 m): ``Z``, de 200 × 100 m (**2 ha**, en los dos sectores), y ``S``, de 40 ×
25 m (0,1 ha, bajo el área mínima). Con los valores de D-5 (1 m y 0,2 ha):

- el aviso sale con ``Z`` sola: 2 ha, 10 · 20.000 = **200.000 m³** y el centro de sus celdas;
- con «explotación hasta la final» en las zonas avisadas, ``Z`` baja a la cota de ancla de
  ``EXPL_10_60_6`` inmediatamente por encima de la final, ``125 + 10·⌈(224,25 − 125)/10⌉ = 225`` m:
  quedan **0,75 m ≤ 1 m**, y pasan del desdoblado a la explotación (234,25 − 225) · 20.000 =
  **185.000 m³** (9.000 celdas en el sector oeste, 83.250 m³, y 11.000 en el este, 101.750 m³),
  que es también lo que la 011 cubica entre la explotación de antes y la de después; ``S`` no
  cambia y ya no queda nada que avisar.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass, replace
from types import MappingProxyType, SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
seeds_mod = import_geoblender("design.seeds")
envelopes = import_geoblender("design.envelopes")
benching = import_geoblender("design.benching")
compose = import_geoblender("design.compose")
messages = import_geoblender("design.messages")
project_model = import_geoblender("core.project.model")
gis_grid = import_geoblender("gis.grid")
zones_mod = import_geoblender("gis.masks.zones")
kernel = import_geoblender("reserves.kernel")
polygons = import_geoblender("reserves.polygons")

RELATIVE = 1e-6
"""La tolerancia frente a la cubicación de la 011 (RF-014-15, CE-014-04)."""
Surface = model.Surface
CellClass = model.CellClass
SectorRef = seeds_mod.SectorRef
SECTORS = (SectorRef("sector_1", "Sector oeste"), SectorRef("sector_2", "Sector este"))
ORDERS = (model.Order.FINAL_FIRST, model.Order.EXPLOITATION_FIRST)
FACE_TOLERANCE_DEG = 1.0
WARNING_RATIO = 2.0


def last_result(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


def close(test: unittest.TestCase, found: float, expected: float, what: str) -> None:
    """``found`` a ≤ :data:`RELATIVE` relativo de ``expected`` (igual si es 0)."""
    test.assertLessEqual(abs(found - expected), RELATIVE * abs(expected),
                         f"{what}: {found!r} frente a {expected!r}")


def at_most(grid: np.ndarray, terrain: np.ndarray) -> np.ndarray:
    """``grid`` sin pasar del terreno donde tiene dato (``≤ z`` de RF-013-14), a mano."""
    return np.where(np.isfinite(terrain), np.minimum(grid, terrain), grid)


@dataclass(frozen=True, slots=True)
class Profile:
    """Un perfil de banco de la prueba: código, altura (m), cara (°), berma (m), ancla (m) y
    factor de malla."""

    code: str
    height_m: float
    face_deg: float
    berm_m: float
    anchor_m: float
    mesh_factor: float

    @property
    def general_tan(self) -> float:
        """La tangente del talud general ``h / (h/tan α + B)``."""
        return self.height_m / (self.height_m / math.tan(math.radians(self.face_deg))
                                + self.berm_m)

    def values(self) -> dict[str, object]:
        return {params.bench_key(self.code, param): value for param, value in (
            ("height_m", self.height_m), ("face_deg", self.face_deg), ("berm_m", self.berm_m),
            ("anchor_m", self.anchor_m), ("mesh_factor", self.mesh_factor))}


class HandMasks:
    """Unas máscaras de mano con lo que leen la cantera y la composición de la 013: la rejilla,
    el corte admitido (``cut``, ya sin la zona a sostener), nada de relleno y una zona «sin
    corte» a sostener (``hold``, que puede estar vacía)."""

    def __init__(self, grid: Any, cut: np.ndarray, hold: np.ndarray) -> None:
        self.grid = grid
        self._cut = cut
        self.zones = {"sin_corte": zones_mod.Runs.from_mask(hold)}
        self.ctypes = MappingProxyType({"sin_corte": "no_cut"})
        self.classes = np.zeros(cut.shape, dtype=np.uint16)
        self.version_uid = "V01"

    def zone(self, code: str) -> Any:
        return self.zones[code]

    def cut_allowed(self) -> np.ndarray:
        return self._cut.copy()

    def fill_allowed(self) -> np.ndarray:
        return np.zeros(self._cut.shape, dtype=bool)

    def fill_strip(self) -> np.ndarray:
        return np.zeros(self._cut.shape, dtype=bool)


def fake_sides(sides: dict[Any, Any]) -> Any:
    """Un ``side_steps`` que da, de cada lado, el resultado ya calculado de ``sides``
    (superficie → ``SideOutcome``)."""

    def side_steps(job: Any, *, budget_s: float = 0.05) -> Any:
        outcome = sides[Surface(job.surface)]
        yield project_model.Progress("side", 1, 1, "lado", result=outcome)

    return side_steps


def side_of(surface: Any, grid: np.ndarray) -> Any:
    """Un ``SideOutcome`` con solo la superficie ``grid`` (las de las piezas de la 013)."""
    return quarry.SideOutcome(surface, None, None, None, None, None,
                              SimpleNamespace(design=grid))


def cubicate(geometry: Any, upper: np.ndarray, lower: np.ndarray, min_thickness_m: float,
             weights: Any = None, domains: int = 0) -> Any:
    """La cubicación de la 011 de ``upper`` frente a ``lower`` (su núcleo, de una vez, con los
    pesos de sus dominios): su ``KernelResult``."""
    found = kernel.Accumulators(geometry, domains=domains, min_thickness_m=min_thickness_m)
    kernel.band_step(found, kernel.BandValues(0, upper, lower), weights)
    return found.result()


def moved_area(result: Any, row: int) -> float:
    """El área con desmonte de una fila de la cubicación (sin terraplén: con dato menos sin
    movimiento)."""
    return float(result.area_m2[row] - result.still_area_m2[row])


def box_ring(geometry: Any, rows: tuple[int, int], cols: tuple[int, int]) -> np.ndarray:
    """El rectángulo ABSOLUTO de las celdas ``rows[0] … rows[1] − 1`` × ``cols[0] … cols[1] −
    1``, por los bordes de celda (sus pesos son 0 o 1)."""
    west = geometry.west + cols[0] * geometry.dx
    east = geometry.west + cols[1] * geometry.dx
    north = geometry.north - rows[0] * geometry.dy
    south = geometry.north - rows[1] * geometry.dy
    return np.array([[west, south], [east, south], [east, north], [west, north]])


def domain_weights(geometry: Any, boxes: list[tuple[tuple[int, int], tuple[int, int]]]) -> Any:
    """Los pesos de la 011 de una capa de dominios con un rectángulo de celdas por dominio."""
    found = tuple(polygons.Polygon(fid, f"d{fid}", (box_ring(geometry, *box),))
                  for fid, box in enumerate(boxes, start=1))
    edges = polygons.domain_edges(found, geometry)
    return polygons.weights([item.edges for item in edges], None, geometry,
                            slice(0, geometry.nrows))


# --- CE-014-04: 100 diseños sintéticos con los dos órdenes ---------------------------------------

DESIGNS = 100
REAL_DESIGNS = 20
"""Los diseños cuyos dos lados calcula ``side_steps``."""
SEED = 14_024
ROWS, COLS = 26, 30
CELL_M = 2.0
GRID = gis_grid.Grid(500_000.0, 4_400_000.0 + ROWS * CELL_M, CELL_M, CELL_M, COLS, ROWS)
"""26 filas × 30 columnas de 2 m (4 m² por celda)."""


@dataclass(frozen=True, slots=True, eq=False)
class Design:
    """Un diseño sintético: su terreno, sus máscaras, su dominio de trabajo, la zona de relleno
    (``fill_box``, filas y columnas; ``None``, ninguna), la primera columna del sector este
    (``split``), las filas con sector (``sector_rows``), el espesor mínimo, la petición, los
    parámetros y sus dos lados ya calculados."""

    index: int
    real: bool
    terrain: np.ndarray
    masks: HandMasks
    domain: Any
    fill_box: tuple[tuple[int, int], tuple[int, int]] | None
    split: int
    sector_rows: int
    min_thickness_m: float
    request: Any
    values: dict[str, object]
    ring_cells: int
    floors: Any
    sides: dict[Any, Any]

    @property
    def fill(self) -> np.ndarray | None:
        if self.fill_box is None:
            return None
        found = np.zeros(GRID.shape, dtype=bool)
        (row0, row1), (col0, col1) = self.fill_box
        found[row0:row1, col0:col1] = True
        return found

    def job(self, order: Any) -> Any:
        return quarry.QuarryJob(
            request=replace(self.request, order=order), start=self.terrain, masks=self.masks,
            domain=self.domain, values=self.values, ring_cells=self.ring_cells,
            min_thickness_m=self.min_thickness_m, face_tolerance_deg=FACE_TOLERANCE_DEG,
            warning_ratio=WARNING_RATIO, floors=self.floors, fill_zones=self.fill)

    def run(self, order: Any) -> Any:
        """``quarry_steps`` con el orden ``order`` y los dos lados del diseño."""
        with mock.patch.object(quarry, "side_steps", fake_sides(self.sides)):
            return last_result(quarry.quarry_steps(self.job(order)))


def random_profile(rng: np.random.Generator, code: str) -> Profile:
    return Profile(code, float(rng.choice([5.0, 7.5, 10.0])), float(rng.uniform(40.0, 75.0)),
                   float(rng.uniform(3.0, 8.0)), float(rng.uniform(100.0, 140.0)),
                   float(rng.choice([1.0, 0.95])))


def random_box(rng: np.random.Generator, rows: tuple[int, int], cols: tuple[int, int],
               size: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """Un rectángulo de celdas de ``size[0]`` a ``size[1]`` de lado dentro de ``rows`` ×
    ``cols``."""
    height, width = (int(rng.integers(size[0], size[1] + 1)) for _ in range(2))
    row0 = int(rng.integers(rows[0], rows[1] - height + 1))
    col0 = int(rng.integers(cols[0], cols[1] - width + 1))
    return (row0, row0 + height), (col0, col0 + width)


def mask_of(box: tuple[tuple[int, int], tuple[int, int]]) -> np.ndarray:
    found = np.zeros(GRID.shape, dtype=bool)
    (row0, row1), (col0, col1) = box
    found[row0:row1, col0:col1] = True
    return found


def floor_map(mask: np.ndarray, level: float) -> Any:
    """Un mapa de fondos de mano: un polígono (``mask``) a la cota ``level``."""
    return quarry.FloorMap("gis_fea_fondos", "cota", np.where(mask, level, np.nan),
                           mask.astype(np.int32), (1,), (level,),
                           (int(np.count_nonzero(mask)),), GRID.cell_area)


def piece_side(rng: np.random.Generator, terrain: np.ndarray, area: np.ndarray,
               profile: Profile, ring_cells: int) -> np.ndarray:
    """Una superficie hecha con las piezas de la 013: la envolvente *chamfer* descendente desde
    unas semillas al azar (la coronación del recinto, más un fondo o cotas sueltas por debajo del
    terreno, o solo cotas sueltas) con el talud general del perfil, su escalonado en corte y su
    composición con el recinto (fuera, el terreno); una de cada cinco, sin componer con el terreno
    dentro del recinto (el escalonado tal cual, que puede quedar por encima del terreno: lo baja el
    ``≤ z`` de la regla de orden)."""
    seeds = np.full(GRID.shape, np.inf)
    kind = int(rng.integers(0, 3))
    if kind < 2:
        crown = quarry.crown_ring(area, terrain, ring_cells)
        seeds[crown] = terrain[crown]
    if kind == 1:
        box = mask_of(random_box(rng, (5, ROWS - 5), (5, COLS - 5), (3, 8)))
        seeds[box & area] = np.nanmin(terrain[box]) - rng.uniform(0.0, 25.0)
    else:
        loose = area & (rng.random(GRID.shape) < rng.uniform(0.01, 0.08))
        seeds[loose] = terrain[loose] - rng.uniform(0.0, 30.0, int(np.count_nonzero(loose)))
    slope = envelopes.SlopeField(profile.general_tan * profile.mesh_factor)
    envelope = last_result(envelopes.chamfer_steps(seeds, GRID, slope, "down",
                                                   name="prueba")).grid
    stairs = benching.bench_cut(envelope, profile.height_m,
                                math.tan(math.radians(profile.face_deg)), profile.berm_m,
                                profile.anchor_m)
    if rng.random() < 0.2:
        return np.where(area & np.isfinite(stairs), stairs, terrain)
    return compose.compose(terrain, stairs, area, "cut")


def make_design(index: int) -> Design:
    """El diseño ``index`` (determinista)."""
    rng = np.random.default_rng(SEED + index)
    rows, cols = np.indices(GRID.shape)
    x, y = (cols + 0.5) * CELL_M, (ROWS - rows - 0.5) * CELL_M
    terrain = (160.0 + rng.uniform(-0.3, 0.3) * x + rng.uniform(-0.3, 0.3) * y
               + rng.uniform(0.0, 3.0) * np.sin(x / rng.uniform(6.0, 15.0))
               * np.cos(y / rng.uniform(6.0, 15.0)))
    if rng.random() < 0.25:  # un hueco sin dato
        (row0, row1), (col0, col1) = random_box(rng, (8, ROWS - 8), (8, COLS - 8), (1, 2))
        terrain[row0:row1, col0:col1] = np.nan
    top, left = (int(value) for value in rng.integers(3, 7, 2))
    bottom, right = ROWS - int(rng.integers(3, 7)), COLS - int(rng.integers(3, 7))
    cut = mask_of(((top, bottom), (left, right)))
    hold = np.zeros(GRID.shape, dtype=bool)
    if rng.random() < 0.6:  # una zona sin corte, a sostener
        hold = mask_of(random_box(rng, (top + 2, bottom - 2), (left + 2, right - 2), (2, 4)))
    masks = HandMasks(GRID, cut & ~hold, hold)
    split = int(rng.integers(9, COLS - 9))
    sector_rows = ROWS if rng.random() < 0.7 else ROWS - int(rng.integers(5, 9))
    labels = np.where(rows < sector_rows, np.where(cols < split, 1, 2), 0).astype(np.int16)
    area = quarry.excavation_area(masks, terrain)
    domain = seeds_mod.domain_of(area, labels, SECTORS, GRID.cell_area)
    fill_box = (random_box(rng, (top, bottom), (left, right), (3, 9))
                if rng.random() < 0.8 else None)
    min_thickness_m = float(rng.choice([0.02, 0.02, 0.1, 0.25]))
    ring_cells = int(rng.integers(1, 4))
    final, exploitation = (random_profile(rng, f"fin_{index}"),
                           random_profile(rng, f"exp_{index}"))
    values = {**final.values(), **exploitation.values()}
    real = index < REAL_DESIGNS
    floors = None
    if real and rng.random() < 0.5:  # un fondo, por debajo del terreno
        floor = mask_of(random_box(rng, (top + 1, bottom - 1), (left + 1, right - 1), (3, 6)))
        floors = floor_map(floor, float(np.nanmin(terrain[floor]) - rng.uniform(3.0, 20.0)))

    def side(profile: Profile) -> Any:
        anchor = "nearest_floor" if floors is not None and rng.random() < 0.5 else "fixed"
        return model.QuarrySide(base_profile=profile.code, anchor=anchor)

    request = model.QuarryRequest(name=f"Diseño {index}", start="gis_dtm_terreno",
                                  final=side(final), exploitation=side(exploitation),
                                  fill_zones="gis_fea_relleno" if fill_box else None)
    design = Design(index, real, terrain, masks, domain, fill_box, split, sector_rows,
                    min_thickness_m, request, values, ring_cells, floors, {})
    if real:
        job = design.job(model.Order.FINAL_FIRST)
        for surface in (Surface.FINAL, Surface.EXPLOITATION):
            design.sides[surface] = last_result(quarry.side_steps(job.side_job(surface)))
    else:
        for surface, profile in ((Surface.FINAL, final), (Surface.EXPLOITATION, exploitation)):
            design.sides[surface] = side_of(surface, piece_side(rng, terrain, area, profile,
                                                                ring_cells))
    return design


class TwoSurfacesDesignsTest(unittest.TestCase):
    """CE-014-04 (RF-014-12 a RF-014-16): 100 diseños sintéticos con los dos órdenes."""

    designs: ClassVar[list[Design]]
    outcomes: ClassVar[dict[tuple[int, Any], Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.designs = [make_design(index) for index in range(DESIGNS)]
        cls.outcomes = {(design.index, order): design.run(order)
                        for design in cls.designs for order in ORDERS}

    def each(self) -> Any:
        for design in self.designs:
            for order in ORDERS:
                yield design, order, self.outcomes[(design.index, order)]

    def test_the_injected_sides_are_those_of_a_whole_calculation(self) -> None:
        """Dar a ``quarry_steps`` los lados ya calculados es lo mismo que calcularlo todo: en el
        primer diseño, con los dos órdenes, las dos superficies bit a bit y la misma
        clasificación."""
        design = self.designs[0]
        self.assertTrue(design.real)
        for order in ORDERS:
            with self.subTest(order=order):
                whole = last_result(quarry.quarry_steps(design.job(order)))
                found = self.outcomes[(0, order)]
                np.testing.assert_array_equal(whole.final_grid, found.final_grid)
                np.testing.assert_array_equal(whole.exploitation_grid, found.exploitation_grid)
                np.testing.assert_array_equal(whole.classes.grid, found.classes.grid)
                self.assertEqual(whole.classes.total, found.classes.total)

    def test_ce04_final_below_exploitation_below_terrain_in_every_cell(self) -> None:
        """CE-014-04, RF-014-14: en todas las celdas de los 200 resultados, ``final ≤ explotación
        ≤ terreno`` sin tolerancia donde el terreno tiene dato y las dos sin dato donde no; fuera
        del recinto, las dos son el terreno."""
        for design, order, outcome in self.each():
            with self.subTest(design=design.index, order=order):
                z = design.terrain
                final, exploitation = outcome.final_grid, outcome.exploitation_grid
                known = np.isfinite(z)
                self.assertTrue(bool(np.all(final[known] <= exploitation[known])))
                self.assertTrue(bool(np.all(exploitation[known] <= z[known])))
                self.assertTrue(bool(np.all(np.isnan(final[~known]))))
                self.assertTrue(bool(np.all(np.isnan(exploitation[~known]))))
                outside = ~design.domain.mask
                np.testing.assert_array_equal(final[outside], z[outside])
                np.testing.assert_array_equal(exploitation[outside], z[outside])

    def test_ce04_the_order_rule_by_hand(self) -> None:
        """CE-014-04, RF-014-13: con «final primero», la final es la de su lado ``≤ z`` y la
        explotación, ``máx(explotación, final)`` ``≤ z``; con «explotación primero», la explotación
        es la de su lado ``≤ z`` y la final, ``mín(final, explotación)`` ``≤ z``; bit a bit. Las
        celdas que la regla cambió son las de la final más de 1 mm por encima de la explotación
        (RF-014-14; T60: no en sentido estricto)."""
        for design, order, outcome in self.each():
            with self.subTest(design=design.index, order=order):
                z = design.terrain
                final = design.sides[Surface.FINAL].grid
                exploitation = design.sides[Surface.EXPLOITATION].grid
                if order is model.Order.FINAL_FIRST:
                    expected = (at_most(final, z), at_most(np.maximum(exploitation, final), z))
                else:
                    expected = (at_most(np.minimum(final, exploitation), z),
                                at_most(exploitation, z))
                np.testing.assert_array_equal(outcome.final_grid, expected[0])
                np.testing.assert_array_equal(outcome.exploitation_grid, expected[1])
                with np.errstate(invalid="ignore"):
                    self.assertEqual(outcome.adjusted, int(np.count_nonzero(
                        final - exploitation > quarry.ORDER_TOLERANCE_M)))
                self.assertIs(outcome.order, order)

    def test_ce04_the_classification_matches_the_011(self) -> None:
        """CE-014-04, RF-014-15: en cada diseño y orden, el desdoblado más el relleno es lo que la
        011 cubica entre la explotación y la final, el relleno es lo que cubica en la zona de
        relleno y el desdoblado lo de fuera de ella; la excavación de la explotación, lo que cubica
        entre el terreno y la explotación; con sus áreas, y por sector (las celdas de ningún
        sector, solo en el total), a ≤ 10⁻⁶ relativo. La 011 no cubica nada de terraplén."""
        for design in self.designs:
            sectors = domain_weights(GRID, [((0, design.sector_rows), (0, design.split)),
                                            ((0, design.sector_rows), (design.split, COLS))])
            fill = None if design.fill_box is None else domain_weights(GRID, [design.fill_box])
            for order in ORDERS:
                outcome = self.outcomes[(design.index, order)]
                with self.subTest(design=design.index, order=order):
                    self.compare(design, outcome, sectors, fill)

    def compare(self, design: Design, outcome: Any, sectors: Any, fill: Any) -> None:
        e = design.min_thickness_m
        z, final, exploitation = design.terrain, outcome.final_grid, outcome.exploitation_grid
        classes = outcome.classes
        total = classes.total
        unsplit, filled = CellClass.UNSPLIT, CellClass.FILL
        self.assertEqual(classes.min_thickness_m, e)
        delta = cubicate(GRID, exploitation, final, e, fill, 0 if fill is None else 1)
        self.assertEqual(float(delta.fill_m3[0]), 0.0)
        close(self, total.unsplit_m3 + total.fill_m3, float(delta.cut_m3[0]), "Δ total")
        close(self, total.area_m2(unsplit) + total.area_m2(filled), moved_area(delta, 0),
              "área de Δ")
        if fill is None:
            self.assertEqual((total.fill_m3, total.fill_cells), (0.0, 0))
        else:
            close(self, total.fill_m3, float(delta.cut_m3[1]), "relleno")
            close(self, total.area_m2(filled), moved_area(delta, 1), "área del relleno")
            close(self, total.unsplit_m3, float(delta.cut_m3[delta.outside]), "desdoblado")
            close(self, total.area_m2(unsplit), moved_area(delta, delta.outside),
                  "área del desdoblado")
        by_sector = cubicate(GRID, exploitation, final, e, sectors, 2)
        dug = cubicate(GRID, z, exploitation, e, sectors, 2)
        self.assertEqual(float(dug.fill_m3[0]), 0.0)
        close(self, total.exp_cut_m3, float(dug.cut_m3[0]), "excavación")
        close(self, total.exp_cut_area_m2, moved_area(dug, 0), "área de la excavación")
        classified = {item.sector.code: item for item in classes.sectors}
        for row, sector in enumerate(SECTORS, start=1):
            item = classified.get(sector.code)
            if item is None:  # un sector sin celdas en el dominio (D-15 de la 013)
                self.assertEqual((float(by_sector.cut_m3[row]), float(dug.cut_m3[row])),
                                 (0.0, 0.0))
                continue
            close(self, item.unsplit_m3 + item.fill_m3, float(by_sector.cut_m3[row]),
                  f"Δ de {sector.code}")
            close(self, item.area_m2(unsplit) + item.area_m2(filled),
                  moved_area(by_sector, row), f"área de Δ de {sector.code}")
            close(self, item.exp_cut_m3, float(dug.cut_m3[row]), f"excavación de {sector.code}")
            close(self, item.exp_cut_area_m2, moved_area(dug, row),
                  f"área de la excavación de {sector.code}")
        self.assertEqual(outcome.figures,
                         quarry.classification_figures(design.request.name, classes))
        self.assertTrue(all(math.isfinite(item.value) for item in outcome.figures))

    def test_ce04_the_designs_have_teeth(self) -> None:
        """Los 100 diseños no son todos iguales: en muchos la regla de orden cambia celdas (con
        los dos órdenes) y los dos órdenes dan superficies distintas; hay desdoblado, relleno de
        restauración y excavación; hay huecos sin dato, zonas a sostener, filas de ningún sector,
        lados por encima del terreno en parte y fondos con el ancla «al fondo de cada muro»."""
        adjusted = {order: sum(1 for design in self.designs
                               if self.outcomes[(design.index, order)].adjusted > 0)
                    for order in ORDERS}
        differ = sum(1 for design in self.designs if not np.array_equal(
            self.outcomes[(design.index, ORDERS[0])].exploitation_grid,
            self.outcomes[(design.index, ORDERS[1])].exploitation_grid, equal_nan=True))
        totals = [outcome.classes.total for _design, _order, outcome in self.each()]
        self.assertGreaterEqual(min(adjusted.values()), 90, adjusted)
        self.assertGreaterEqual(differ, 90)
        self.assertGreaterEqual(sum(1 for item in totals if item.unsplit_m3 > 0.0), 180)
        self.assertGreaterEqual(sum(1 for item in totals if item.fill_m3 > 0.0), 90)
        self.assertEqual(sum(1 for item in totals if item.exp_cut_m3 > 0.0), 2 * DESIGNS)
        self.assertGreaterEqual(sum(1 for design in self.designs
                                    if np.isnan(design.terrain).any()), 20)
        self.assertGreaterEqual(sum(1 for design in self.designs
                                    if design.sector_rows < ROWS), 20)
        self.assertGreaterEqual(sum(1 for design in self.designs
                                    if design.masks.zones["sin_corte"].mask(GRID.shape).any()), 50)
        with np.errstate(invalid="ignore"):
            above = sum(1 for design in self.designs if any(
                bool(np.any(side.grid > design.terrain)) for side in design.sides.values()))
        self.assertGreaterEqual(above, 15)
        real = [design for design in self.designs if design.real]
        self.assertGreaterEqual(sum(1 for design in real for order in ORDERS
                                    if self.outcomes[(design.index, order)].adjusted > 0), 30)
        self.assertGreaterEqual(sum(1 for design in real for order in ORDERS if self.outcomes[(
            design.index, order)].classes.total.unsplit_m3 > 0.0), 30)
        sides = [side for design in real for side in (design.request.final,
                                                      design.request.exploitation)]
        anchors = [model.AnchorMode(side.anchor) for side in sides]
        self.assertGreaterEqual(anchors.count(model.AnchorMode.NEAREST_FLOOR), 10)


# --- CE-014-05: «explotación hasta la final» (error 60) -------------------------------------------

MESETA_M = 234.25
"""El terreno de la meseta (m, exacto en binario)."""
PIT_M = 225.0
"""La explotación y la final excavadas en el recinto (m): sin diferencia."""
FINAL_M = 224.25
"""La final de las dos zonas sin explotar: 10 m por debajo del terreno."""
LEVEL_M = 125.0 + 10.0 * math.ceil((FINAL_M - 125.0) / 10.0)
"""La cota de ancla de ``EXPL_10_60_6`` (125 m, 10 m) inmediatamente por encima de la final:
225 m."""
ZONE_LOCAL = (100.0, 160.0, 300.0, 260.0)
"""La zona ``Z`` de 2 ha (200 × 100 m, local), en los dos sectores (9.000 celdas al oeste de
x = 190 y 11.000 al este)."""
SMALL_LOCAL = (200.0, 290.0, 240.0, 315.0)
"""La zona ``S`` de 0,1 ha (40 × 25 m, local), a 30 m de ``Z``, en el sector este."""
AREA_BOX = (45.0, 60.0, 355.0, 340.0)
"""El rectángulo del recinto de la cantera antes de quitar la torre y «sin corte» (T14)."""
ZONE_CELLS, SMALL_CELLS = 20_000, 1_000
WEST_CELLS, EAST_CELLS = 9_000, 11_000
WARNED_M3 = (MESETA_M - FINAL_M) * ZONE_CELLS
"""El volumen de la zona avisada: 10 · 20.000 = 200.000 m³."""
PASSED_M3 = (MESETA_M - LEVEL_M) * ZONE_CELLS
"""Lo que pasa a la explotación: 9,25 · 20.000 = 185.000 m³."""


def tower_by_hand() -> np.ndarray:
    """La zona de la torre de la cantera (T14): las celdas que tocan el disco abierto de 8 m."""
    x, y = qfx.local_centers()
    tx, ty = qfx.TOWER_LOCAL
    dx = np.maximum(np.abs(x - tx) - 0.5, 0.0)
    dy = np.maximum(np.abs(y - ty) - 0.5, 0.0)
    return dx * dx + dy * dy < qfx.TOWER_OUTWARD_M ** 2


def cantera_case() -> dict[str, Any]:
    """La meseta sobre la rejilla, el recinto y los sectores de la cantera, con las dos
    superficies (véase el módulo)."""
    area = qfx.in_box(AREA_BOX) & ~tower_by_hand() & ~qfx.in_box(qfx.NO_CUT_LOCAL)
    x, _y = qfx.local_centers()
    sector_area = qfx.in_box(qfx.PERIMETER_LOCAL)
    labels = np.where(sector_area, np.where(x < 190.0, 1, 2), 0).astype(np.int16)
    terrain = np.full(qfx.GRID.shape, MESETA_M)
    zone, small = qfx.in_box(ZONE_LOCAL), qfx.in_box(SMALL_LOCAL)
    exploitation = np.where(area, PIT_M, terrain)
    final = exploitation.copy()
    for mask in (zone, small):
        exploitation[mask], final[mask] = MESETA_M, FINAL_M
    return {"terrain": terrain, "exploitation": exploitation, "final": final, "zone": zone,
            "small": small, "domain": seeds_mod.domain_of(area, labels, SECTORS,
                                                           qfx.GRID.cell_area)}


def cantera_job(case: dict[str, Any], to_final: str) -> Any:
    expl, rest = qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE
    values: dict[str, object] = {}
    for profile in (expl, rest):
        values.update(Profile(profile.code, profile.height_m, profile.face_deg, profile.berm_m,
                              profile.anchor_m, profile.mesh_factor).values())
    request = model.QuarryRequest(
        name="Cantera E4", start=qfx.START_DATASET,
        final=model.QuarrySide(base_profile=rest.code),
        exploitation=model.QuarrySide(base_profile=expl.code), to_final=to_final)
    return quarry.QuarryJob(
        request=request, start=case["terrain"], masks=SimpleNamespace(grid=qfx.GRID),
        domain=case["domain"], values=values, ring_cells=3, min_thickness_m=0.02,
        face_tolerance_deg=FACE_TOLERANCE_DEG, warning_ratio=WARNING_RATIO,
        unsplit_threshold_m=params.QUARRY_PARAMS[params.UNSPLIT_THRESHOLD].default,
        unsplit_min_area_ha=params.QUARRY_PARAMS[params.UNSPLIT_MIN_AREA].default)


class ToFinalReferenceTest(unittest.TestCase):
    """CE-014-05 (RF-014-17, RF-014-18): la zona de 2 ha sin explotar, avisada y bajada."""

    case: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = cantera_case()
        sides = {Surface.FINAL: side_of(Surface.FINAL, cls.case["final"]),
                 Surface.EXPLOITATION: side_of(Surface.EXPLOITATION, cls.case["exploitation"])}
        with mock.patch.object(quarry, "side_steps", fake_sides(sides)):
            cls.none = last_result(quarry.quarry_steps(cantera_job(cls.case, "none")))
            cls.warned = last_result(quarry.quarry_steps(cantera_job(cls.case, "warned")))

    def test_ce05_the_case_by_hand(self) -> None:
        """El caso: el recinto de la cantera (84.976 celdas, T14) en los dos sectores; ``Z``, de
        20.000 celdas (2 ha) con 9.000 en el oeste y 11.000 en el este, y ``S``, de 1.000 (0,1
        ha), dentro de él; la cota de ancla por encima de la final, 225 m; D-5, 1 m y 0,2 ha."""
        domain = self.case["domain"]
        self.assertEqual(domain.cells, qfx.CUT_ALLOWED_CELLS)
        zone, small = self.case["zone"], self.case["small"]
        self.assertEqual((int(np.count_nonzero(zone)), int(np.count_nonzero(small))),
                         (ZONE_CELLS, SMALL_CELLS))
        self.assertTrue(bool(np.all(domain.mask[zone | small])))
        self.assertEqual(int(np.count_nonzero(zone & (domain.labels == 1))), WEST_CELLS)
        self.assertEqual(int(np.count_nonzero(zone & (domain.labels == 2))), EAST_CELLS)
        self.assertEqual(LEVEL_M, 225.0)
        self.assertEqual((WARNED_M3, PASSED_M3), (200_000.0, 185_000.0))
        self.assertEqual((params.QUARRY_PARAMS[params.UNSPLIT_THRESHOLD].default,
                          params.QUARRY_PARAMS[params.UNSPLIT_MIN_AREA].default), (1.0, 0.2))

    def test_ce05_the_2_ha_zone_is_warned(self) -> None:
        """CE-014-05, RF-014-17 (error 60): sin el modo, el aviso sale con la zona ``Z``: 2 ha,
        200.000 m³ y el centro de sus celdas en absolutas, (x0 + 200, y0 + 210); ``S`` es de las
        celdas del aviso (10 m sobre terreno sin explotar) pero no llega al área mínima. El aviso
        ofrece «Explotación hasta la final»; la explotación no cambia."""
        unsplit = self.none.unsplit
        self.assertEqual([(zone.cells, zone.area_m2, zone.volume_m3) for zone in unsplit.zones],
                         [(ZONE_CELLS, 20_000.0, WARNED_M3)])
        (zone,) = unsplit.zones
        self.assertEqual(zone.area_ha, 2.0)
        self.assertEqual((zone.x, zone.y), (qfx.BASE[0] + 200.0, qfx.BASE[1] + 210.0))
        np.testing.assert_array_equal(unsplit.candidates, self.case["zone"] | self.case["small"])
        np.testing.assert_array_equal(unsplit.warned, self.case["zone"])
        warning, note = self.none.notices
        self.assertEqual(warning, messages.render(
            "des.quarry_unsplit_zones", zones=1, area=2.0, volume=WARNED_M3, threshold=1.0,
            min_area=0.2))
        self.assertIn("«Explotación hasta la final»", warning)
        self.assertEqual(note, messages.render("des.quarry_unsplit_zone", zone=zone.zone,
                                               area=2.0, volume=WARNED_M3,
                                               x=qfx.BASE[0] + 200.0, y=qfx.BASE[1] + 210.0))
        self.assertIsNone(self.none.to_final)
        np.testing.assert_array_equal(self.none.exploitation_grid, self.case["exploitation"])
        self.assertEqual(self.none.classes.total.unsplit_m3, WARNED_M3 + 10.0 * SMALL_CELLS)

    def test_ce05_down_to_the_final_leaves_at_most_1_m(self) -> None:
        """CE-014-05, RF-014-18: con «explotación hasta la final» en las zonas avisadas, ``Z`` baja
        a 225 m exactos (la cota de ancla inmediatamente por encima de la final): quedan 0,75 m
        ≤ 1 m y nunca por debajo de la final; ``S`` y el resto no cambian (la transición, a la cara
        de ``EXPL_10_60_6``, no llega a ``S``) y ``final ≤ explotación ≤ terreno``."""
        exploitation, final = self.warned.exploitation_grid, self.warned.final_grid
        zone = self.case["zone"]
        np.testing.assert_array_equal(exploitation[zone], LEVEL_M)
        rest = exploitation[zone] - final[zone]
        self.assertEqual(float(rest.max()), 0.75)
        self.assertLessEqual(float(rest.max()), 1.0)
        np.testing.assert_array_equal(exploitation[~zone], self.case["exploitation"][~zone])
        np.testing.assert_array_equal(final, self.case["final"])
        self.assertTrue(bool(np.all(final <= exploitation)))
        self.assertTrue(bool(np.all(exploitation <= self.case["terrain"])))
        self.assertEqual(self.warned.to_final.lowered_cells, ZONE_CELLS)

    def test_ce05_the_volume_that_passes_by_hand_and_with_the_011(self) -> None:
        """CE-014-05, RF-014-18: pasan del desdoblado a la explotación (234,25 − 225) · 20.000 =
        185.000 m³ (83.250 en el sector oeste y 101.750 en el este), con su cifra CALCULADO
        ``des.to_final_m3`` en total y por sector; y la cubicación de la 011 entre la explotación
        de antes y la de después da lo mismo, sin terraplén."""
        found = self.warned.to_final
        self.assertEqual(found.volume_m3, PASSED_M3)
        self.assertEqual(dict(found.sectors), {SECTORS[0]: 9.25 * WEST_CELLS,
                                               SECTORS[1]: 9.25 * EAST_CELLS})
        self.assertEqual({item.scope.get("sector"): item.value for item in self.warned.figures
                          if item.key == "des.to_final_m3"},
                         {None: PASSED_M3, "sector_1": 83_250.0, "sector_2": 101_750.0})
        weights = domain_weights(qfx.GRID, [((0, qfx.SIZE), (0, 190)),
                                            ((0, qfx.SIZE), (190, qfx.SIZE))])
        cubication = cubicate(qfx.GRID, self.none.exploitation_grid,
                              self.warned.exploitation_grid, 0.0, weights, 2)
        self.assertEqual(float(cubication.fill_m3[0]), 0.0)
        close(self, float(cubication.cut_m3[0]), PASSED_M3, "lo que pasa (011)")
        close(self, float(cubication.cut_m3[1]), 83_250.0, "lo que pasa en el oeste (011)")
        close(self, float(cubication.cut_m3[2]), 101_750.0, "lo que pasa en el este (011)")

    def test_ce05_what_is_left_after_the_mode(self) -> None:
        """Con el modo, la clasificación se rehace: el desdoblado baja en los 185.000 m³ que pasan
        (quedan 0,75 · 20.000 + 10 · 1.000 = 25.000 m³), la excavación de la explotación sube en
        ellos, ya no queda nada que avisar (0,75 m no pasa del umbral y ``S`` no llega al área
        mínima) y la nota dice lo que pasó."""
        before, after = self.none.classes.total, self.warned.classes.total
        self.assertEqual(after.unsplit_m3, 0.75 * ZONE_CELLS + 10.0 * SMALL_CELLS)
        self.assertEqual(before.unsplit_m3 - after.unsplit_m3, PASSED_M3)
        self.assertEqual(after.exp_cut_m3 - before.exp_cut_m3, PASSED_M3)
        self.assertEqual(self.warned.unsplit.zones, ())
        note = messages.render("des.quarry_to_final", zones=1, area=2.0, volume=PASSED_M3)
        self.assertEqual(self.warned.notices, (note,))


if __name__ == "__main__":
    unittest.main()
