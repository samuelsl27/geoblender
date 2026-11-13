# SPDX-License-Identifier: GPL-3.0-or-later
"""La clasificación y las cifras de las dos superficies de la cantera (spec 014, T17; HU-014-3;
RF-014-15, RF-014-16; plan 014 A8, §5.2.3).

``design.quarry.classify_steps`` clasifica cada celda del dominio de trabajo con ``Δ = explotación
− final`` y el espesor mínimo ``e`` de la 012: **sin diferencia** si ``Δ ≤ e``, **relleno** si
``Δ > e`` dentro de una zona de restauración por relleno (la capa de D-11) y **desdoblado** si no;
y da, en total y por sector, la excavación de la explotación (``terreno − explotación`` con el
mismo ``e``), el desdoblado y el relleno en m³ (``Σ Δ · área de celda``, la fórmula celda a celda
de la cubicación de la 011), sus áreas y las cotas mínima y máxima de cada superficie.
``classification_figures`` las lleva a cifras CALCULADO (RF-014-16) y ``quarry_steps`` las da con
las dos superficies.

Las reglas y las cifras, con una rejilla a mano; los volúmenes, **frente a la cubicación de la
011** (``reserves.volumes.volume_steps``) sobre las mismas rejillas escritas como GeoTIFF, a ≤ 10⁻⁶
relativo (la prueba importa ``reserves``; ``design`` no): las zonas de relleno y los sectores, como
dominios de la cubicación (rectángulos en los bordes de celda: su peso es 0 o 1). Primero en una
rejilla sintética con empates exactos en ``Δ = e`` y después en la cantera de
``tests.support.quarry_fixtures`` (E3 y un reparto con desdoblado y relleno).
"""

from __future__ import annotations

import math
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
seeds_mod = import_geoblender("design.seeds")
zones = import_geoblender("design.zones")
gis = import_geoblender("gis")
gis_grid = import_geoblender("gis.grid")
writer = import_geoblender("gis.geotiff.writer")
volumes = import_geoblender("reserves.volumes")
surfaces = import_geoblender("reserves.surfaces")
polygons = import_geoblender("reserves.polygons")
figures_module = import_geoblender("core.provenance.figures")

NAN = math.nan
RELATIVE = 1e-6
"""La tolerancia frente a la cubicación de la 011 (RF-014-15, CE-014-04)."""
CellClass = model.CellClass
Surface = model.Surface
SectorRef = seeds_mod.SectorRef
SECTORS = (SectorRef("sector_1", "Sector oeste"), SectorRef("sector_2", "Sector este"))
VOLUME_KEYS = ("des.exp_cut_m3", "des.unsplit_m3", "des.restoration_fill_m3")
AREA_KEYS = ("des.exp_cut_area_ha", "des.unsplit_area_ha", "des.restoration_fill_area_ha")
LEVEL_KEYS = ("des.quarry_min_m", "des.quarry_max_m")


def last_result(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


def close(test: unittest.TestCase, found: float, expected: float, what: str) -> None:
    """``found`` a ≤ :data:`RELATIVE` relativo de ``expected`` (igual si es 0)."""
    test.assertLessEqual(abs(found - expected), RELATIVE * abs(expected),
                         f"{what}: {found!r} frente a {expected!r}")


# --- La regla y las cifras, a mano ---------------------------------------------------------------

GRID = gis_grid.Grid(500_000.0, 4_400_006.0, 2.0, 2.0, 4, 3)
"""3 × 4 celdas de 2 m (4 m² cada una)."""
E = 0.25
"""El espesor mínimo de la prueba (m)."""
TERRAIN = np.array([[110.0, 111.0, 112.0, 113.0],
                    [109.0, 110.0, 111.0, 112.0],
                    [108.0, 109.0, 110.0, NAN]])
EXPLOITATION = np.array([[104.0, 111.0, 106.0, 113.0],
                         [101.0, 107.0, 111.0, 100.0],
                         [108.0, 105.0, 103.0, NAN]])
FINAL = np.array([[100.0, 111.0, 106.0, 112.75],
                  [100.5, 106.5, NAN, 97.0],
                  [107.5, 105.0005, 100.0, NAN]])
"""``Δ`` = [[4, 0, 0, 0,25], [0,5, 0,5, —, 3], [0,5, −0,0005, 3, —]]: un empate exacto en ``e``
(0, 3), la final 0,5 mm por encima de la explotación (2, 1: dentro del milímetro de RF-014-14) y
una celda sin final (1, 2)."""
DOMAIN = np.array([[True, True, True, True],
                   [True, True, True, True],
                   [True, True, True, False]])
"""El dominio de trabajo: todo menos la celda (2, 3)."""
LABELS = np.array([[1, 1, 2, 2],
                   [1, 1, 2, 2],
                   [1, 1, 0, 2]], dtype=np.int16)
"""``sector_1`` las columnas 0 y 1; ``sector_2`` las 2 y 3, salvo la (2, 2), de ningún sector."""
FILL = np.array([[True, True, False, False],
                 [True, False, False, False],
                 [False, False, False, True]])
"""Las zonas de restauración por relleno: (0, 0), (0, 1), (1, 0) y la (2, 3), fuera del dominio."""
CODES = np.array([[2.0, 0.0, 0.0, 0.0],
                  [2.0, 1.0, NAN, 1.0],
                  [1.0, 0.0, 1.0, NAN]])
"""La clasificación a mano: relleno (0, 0) y (1, 0); desdoblado (1, 1), (1, 3), (2, 0) y (2, 2);
sin diferencia (0, 1) —en la zona de relleno pero con Δ = 0—, (0, 2), (0, 3) —Δ = e— y (2, 1);
sin dato (1, 2) y la (2, 3), fuera del dominio."""


def domain_set(mask: np.ndarray = DOMAIN, labels: np.ndarray = LABELS,
               geometry: Any = GRID) -> Any:
    return seeds_mod.domain_of(mask, labels, SECTORS, geometry.cell_area)


def classify(**changes: Any) -> Any:
    values: dict[str, Any] = {
        "final": FINAL, "exploitation": EXPLOITATION, "start": TERRAIN, "domain": domain_set(),
        "geometry": GRID, "min_thickness_m": E, "fill_zones": FILL}
    values.update(changes)
    return last_result(quarry.classify_steps(**values))


class ClassRuleTest(unittest.TestCase):
    """RF-014-15: la clase de cada celda y sus volúmenes, a mano."""

    def test_each_cell_gets_its_class(self) -> None:
        """La rejilla de la clasificación lleva el código de cada clase (``CellClass.code``: 0
        sin diferencia, 1 desdoblado, 2 relleno) en las celdas del dominio con las dos superficies
        y sin dato fuera de él o donde falta una: ``Δ ≤ e`` (también el empate exacto y la final
        medio milímetro por encima) es sin diferencia; ``Δ > e`` en la zona de relleno, relleno; y
        si no, desdoblado. Una rejilla nueva de float64 (P-1: GeoTIFF con sin dato). El nombre de
        cada clase (RF-014-16, T51): el de la vista y la barra N, «relleno de restauración»."""
        found = classify()
        self.assertIsInstance(found, quarry.Classification)
        self.assertEqual(found.grid.dtype, np.float64)
        np.testing.assert_array_equal(found.grid, CODES)
        self.assertEqual((CellClass.NONE.code, CellClass.UNSPLIT.code, CellClass.FILL.code),
                         (0, 1, 2))
        self.assertEqual(found.min_thickness_m, E)
        self.assertEqual(found.cell_area_m2, 4.0)
        self.assertEqual(dict(quarry.CLASS_NAMES), {
            CellClass.NONE: "sin diferencia", CellClass.UNSPLIT: "desdoblado",
            CellClass.FILL: "relleno de restauración"})

    def test_volumes_and_areas_in_total(self) -> None:
        """El total: relleno 4 + 0,5 = 4,5 m de Δ (18 m³, 2 celdas, 8 m²); desdoblado 0,5 + 3 +
        0,5 + 3 = 7 m (28 m³, 4 celdas); sin diferencia, 4 celdas; sin dato, 1; la excavación de la
        explotación (``terreno − explotación > e``) 6 + 6 + 8 + 3 + 12 + 4 + 7 = 46 m (184 m³, 7
        celdas); 11 celdas del dominio. Las áreas en m² y en ha (RF-014-16)."""
        total = classify().total
        self.assertIsNone(total.sector)
        self.assertEqual(total.cells, 11)
        self.assertEqual(total.nodata_cells, 1)
        self.assertEqual((total.cells_of(CellClass.FILL), total.cells_of(CellClass.UNSPLIT),
                          total.cells_of(CellClass.NONE)), (2, 4, 4))
        self.assertEqual((total.fill_m3, total.unsplit_m3), (18.0, 28.0))
        self.assertEqual(total.volume_m3(CellClass.FILL), 18.0)
        self.assertEqual(total.volume_m3(CellClass.UNSPLIT), 28.0)
        self.assertEqual(total.volume_m3(CellClass.NONE), 0.0)
        self.assertEqual((total.area_m2(CellClass.FILL), total.area_m2(CellClass.UNSPLIT),
                          total.area_m2(CellClass.NONE)), (8.0, 16.0, 16.0))
        self.assertAlmostEqual(total.area_ha(CellClass.UNSPLIT), 0.0016, delta=1e-15)
        self.assertEqual((total.exp_cut_m3, total.exp_cut_cells, total.exp_cut_area_m2),
                         (184.0, 7, 28.0))
        self.assertAlmostEqual(total.exp_cut_area_ha, 0.0028, delta=1e-15)

    def test_levels_of_each_surface_over_the_domain(self) -> None:
        """Las cotas mínima y máxima de cada superficie, en las celdas del dominio con dato:
        la final de 97 a 112,75 m y la explotación de 100 a 113 m (la celda fuera del dominio no
        cuenta)."""
        total = classify().total
        self.assertEqual((total.final_min_m, total.final_max_m), (97.0, 112.75))
        self.assertEqual((total.exploitation_min_m, total.exploitation_max_m), (100.0, 113.0))
        self.assertEqual(total.levels(Surface.FINAL), (97.0, 112.75))
        self.assertEqual(total.levels("exploitation"), (100.0, 113.0))

    def test_by_sector(self) -> None:
        """Por sector (RF-014-16), con las etiquetas del dominio: ``sector_1`` (6 celdas) relleno 18
        m³, desdoblado 0,5 + 0,5 = 1 m (4 m³, 2 celdas), excavación 6 + 8 + 3 + 4 = 21 m (84 m³),
        final de 100 a 111 m y explotación de 101 a 111 m; ``sector_2`` (4 celdas, una sin dato)
        desdoblado 3 m (12 m³), excavación 6 + 12 = 18 m (72 m³), final de 97 a 112,75 m y
        explotación de 100 a 113 m. La celda de ningún sector (desdoblado 3 m, excavación 7 m)
        cuenta solo en el total."""
        found = classify()
        self.assertEqual(tuple(item.sector for item in found.sectors), SECTORS)
        one, two = found.sector("sector_1"), found.sector("sector_2")
        self.assertIs(one, found.sectors[0])
        self.assertEqual((one.cells, one.nodata_cells, one.fill_m3, one.unsplit_m3,
                          one.cells_of(CellClass.UNSPLIT), one.cells_of(CellClass.NONE),
                          one.exp_cut_m3, one.exp_cut_cells),
                         (6, 0, 18.0, 4.0, 2, 2, 84.0, 4))
        self.assertEqual((one.levels(Surface.FINAL), one.levels(Surface.EXPLOITATION)),
                         ((100.0, 111.0), (101.0, 111.0)))
        self.assertEqual((two.cells, two.nodata_cells, two.fill_m3, two.unsplit_m3,
                          two.cells_of(CellClass.UNSPLIT), two.cells_of(CellClass.NONE),
                          two.exp_cut_m3, two.exp_cut_cells),
                         (4, 1, 0.0, 12.0, 1, 2, 72.0, 2))
        self.assertEqual((two.levels(Surface.FINAL), two.levels(Surface.EXPLOITATION)),
                         ((97.0, 112.75), (100.0, 113.0)))
        with self.assertRaises(KeyError):
            found.sector("sector_3")

    def test_without_fill_zones_everything_moved_is_unsplit(self) -> None:
        """Sin capa de zonas de restauración por relleno no hay relleno: lo que pasa de ``e`` es
        desdoblado (4,5 + 7 = 11,5 m, 46 m³)."""
        found = classify(fill_zones=None)
        np.testing.assert_array_equal(found.grid, np.where(CODES == 2.0, 1.0, CODES))
        self.assertEqual((found.total.fill_m3, found.total.unsplit_m3), (0.0, 46.0))

    def test_a_sector_without_cells_in_the_domain_has_no_row(self) -> None:
        """Solo los sectores que toca el dominio (D-15 de la 013) tienen su reparto."""
        mask = DOMAIN & (LABELS != 2)
        found = classify(domain=domain_set(mask))
        self.assertEqual(tuple(item.sector for item in found.sectors), SECTORS[:1])
        self.assertEqual(found.total.cells, 7)

    def test_the_inputs_do_not_change(self) -> None:
        before = [array.copy() for array in (FINAL, EXPLOITATION, TERRAIN, FILL, DOMAIN, LABELS)]
        classify()
        for old, new in zip(before, (FINAL, EXPLOITATION, TERRAIN, FILL, DOMAIN, LABELS),
                            strict=True):
            np.testing.assert_array_equal(old, new)


class ClassStepsTest(unittest.TestCase):
    """Los pasos (§5.3.2) y los errores del programa."""

    def test_by_bands_it_is_the_same(self) -> None:
        """Con una fila por unidad y sin presupuesto, un paso por fila (fase ``classes``) y solo
        el último lleva el resultado, el mismo que de una vez."""
        steps = list(quarry.classify_steps(FINAL, EXPLOITATION, TERRAIN, domain_set(), GRID, E,
                                           fill_zones=FILL, budget_s=1e-9, cells_per_unit=1))
        self.assertGreaterEqual(len(steps), 4)
        self.assertTrue(all(step.phase == "classes" for step in steps))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        found, whole = steps[-1].result, classify()
        np.testing.assert_array_equal(found.grid, whole.grid)
        self.assertEqual(found.total, whole.total)
        self.assertEqual(found.sectors, whole.sectors)

    def test_closing_half_way_leaves_nothing(self) -> None:
        steps = quarry.classify_steps(FINAL, EXPLOITATION, TERRAIN, domain_set(), GRID, E,
                                      fill_zones=FILL, budget_s=1e-9, cells_per_unit=1)
        next(steps)
        steps.close()

    def test_the_final_above_the_exploitation_is_a_program_error(self) -> None:
        """Más de 1 mm de la final por encima de la explotación (1,1 mm) no se clasifica: las
        superficies no vienen de la regla de orden (RF-014-14)."""
        final = FINAL.copy()
        final[2, 1] = 105.0011
        with self.assertRaises(ValueError):
            classify(final=final)

    def test_bad_inputs_are_program_errors_when_calling(self) -> None:
        for changes in ({"final": FINAL[:, :3]}, {"fill_zones": FILL[:2]},
                        {"min_thickness_m": -0.1}, {"min_thickness_m": NAN},
                        {"domain": domain_set(np.ones((2, 2), bool), np.ones((2, 2), np.int16),
                                              gis_grid.Grid(0.0, 4.0, 2.0, 2.0, 2, 2))}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                values: dict[str, Any] = {
                    "final": FINAL, "exploitation": EXPLOITATION, "start": TERRAIN,
                    "domain": domain_set(), "geometry": GRID, "min_thickness_m": E,
                    "fill_zones": FILL}
                values.update(changes)
                quarry.classify_steps(**values)


class FiguresTest(unittest.TestCase):
    """RF-014-16: las cifras CALCULADO de la clasificación, en total y por sector."""

    def test_the_figures_of_the_hand_grid(self) -> None:
        """Por reparto (el total, ``sector_1`` y ``sector_2``): la excavación de la explotación, el
        desdoblado y el relleno en m³, sus áreas en ha y las cotas mínima y máxima de cada
        superficie (con la superficie en su ámbito); el ámbito, el de ``quarry_figure_scope``."""
        provenance = import_geoblender("design.provenance")
        found = quarry.classification_figures("Cantera a mano", classify())
        by_key = {(item.key, figures_module.scope_json(item.scope)): item for item in found}
        self.assertEqual(len(by_key), len(found))
        self.assertEqual(len(found), 3 * (len(VOLUME_KEYS) + len(AREA_KEYS) + 2 * 2))
        for item in found:
            self.assertEqual(item.kind, figures_module.ParamKind.CALCULADO)
            self.assertTrue(math.isfinite(item.value))

        def value(key: str, **scope: Any) -> float:
            text = figures_module.scope_json(provenance.quarry_figure_scope("Cantera a mano",
                                                                            **scope))
            return by_key[(key, text)].value

        self.assertEqual(value("des.exp_cut_m3"), 184.0)
        self.assertEqual(value("des.unsplit_m3"), 28.0)
        self.assertEqual(value("des.restoration_fill_m3"), 18.0)
        self.assertAlmostEqual(value("des.exp_cut_area_ha"), 0.0028, delta=1e-15)
        self.assertAlmostEqual(value("des.unsplit_area_ha"), 0.0016, delta=1e-15)
        self.assertAlmostEqual(value("des.restoration_fill_area_ha"), 0.0008, delta=1e-15)
        self.assertEqual(value("des.quarry_min_m", surface="final"), 97.0)
        self.assertEqual(value("des.quarry_max_m", surface="exploitation"), 113.0)
        self.assertEqual(value("des.unsplit_m3", sector="sector_1"), 4.0)
        self.assertEqual(value("des.exp_cut_m3", sector="sector_2"), 72.0)
        self.assertEqual(value("des.quarry_min_m", surface="exploitation", sector="sector_1"),
                         101.0)
        units = {item.key: item.unit for item in found}
        self.assertEqual(units, {**dict.fromkeys(VOLUME_KEYS, "m3"),
                                 **dict.fromkeys(AREA_KEYS, "ha"),
                                 **dict.fromkeys(LEVEL_KEYS, "m")})
        declared = {item.key: item.unit for item in provenance.TWO_SURFACES_FIGURES}
        for key, unit in units.items():
            self.assertEqual(declared[key], unit)

    def test_the_whole_perimeter_as_its_only_sector_has_no_sector_figures(self) -> None:
        """Sin sectores declarados, el perímetro es el sector único (código vacío): sus cifras
        serían las del total y no se repiten."""
        whole = seeds_mod.domain_of(DOMAIN, DOMAIN.astype(np.int16),
                                    (SectorRef("", "Perímetro de actuación"),), GRID.cell_area)
        found = quarry.classification_figures("Cantera a mano", classify(domain=whole))
        self.assertEqual(len(found), len(VOLUME_KEYS) + len(AREA_KEYS) + 2 * 2)
        self.assertTrue(all("sector" not in item.scope for item in found))


# --- Frente a la cubicación de la 011 ------------------------------------------------------------


def write_grid(path: Path, values: np.ndarray, geometry: Any) -> Any:
    """``values`` como GeoTIFF del perfil ``project`` (float64, sin dato NaN) y su fuente de la
    011."""
    writer.write_geotiff(gis.Raster(geometry, values, qfx.CRS, qfx.VERTICAL), path,
                         profile="project")
    return surfaces.grid_source(path, name=path.stem, crs=qfx.CRS, vertical=qfx.VERTICAL)


def cell_box(geometry: Any, rows: tuple[int, int], cols: tuple[int, int]) -> np.ndarray:
    """El rectángulo ABSOLUTO de las celdas ``rows[0] … rows[1] − 1`` × ``cols[0] … cols[1] −
    1`` de ``geometry``, por los bordes de celda."""
    west = geometry.west + cols[0] * geometry.dx
    east = geometry.west + cols[1] * geometry.dx
    north = geometry.north - rows[0] * geometry.dy
    south = geometry.north - rows[1] * geometry.dy
    return np.array([[west, south], [east, south], [east, north], [west, north]])


def domains(name: str, boxes: dict[str, np.ndarray]) -> Any:
    return volumes.DomainLayer(name, "nombre", tuple(
        polygons.Polygon(fid, value, (ring,))
        for fid, (value, ring) in enumerate(boxes.items(), start=1)))


def cubication(start: Any, final: Any, min_thickness_m: float, layer: Any = None) -> Any:
    """La cubicación de la 011 de ``start`` frente a ``final`` (sus ``SurfaceSource``) con el
    espesor mínimo y, si se da, la capa de dominios: su ``KernelResult``."""
    request = volumes.VolumeRequest("Comprobación", surfaces.SurfaceRef(dataset="arriba"),
                                    surfaces.SurfaceRef(dataset="abajo"), domains=layer,
                                    min_thickness_m=min_thickness_m)
    return last_result(volumes.volume_steps(request, {"start": start, "final": final})).kernel


def moved_area(kernel: Any, row: int) -> float:
    """El área con desmonte de una fila de la cubicación (sin terraplén: con dato menos sin
    movimiento)."""
    return float(kernel.area_m2[row] - kernel.still_area_m2[row])


class ReservesMixin:
    """La comparación de una clasificación con la cubicación de la 011 sobre las mismas rejillas:
    ``Δ`` con el reparto de las zonas de relleno y con el de los sectores, y la excavación de la
    explotación con el de los sectores."""

    def compare_with_the_011(self: Any, found: Any, sources: dict[str, Any], fill: dict,
                             sectors: dict) -> None:
        unsplit, filled = CellClass.UNSPLIT, CellClass.FILL
        e = found.min_thickness_m
        total = found.total
        by_fill = cubication(sources["exploitation"], sources["final"], e,
                             domains("Relleno", fill) if fill else None)
        self.assertEqual(float(by_fill.fill_m3[0]), 0.0)
        close(self, total.unsplit_m3 + total.fill_m3, float(by_fill.cut_m3[0]), "Δ total")
        close(self, total.area_m2(unsplit) + total.area_m2(filled), moved_area(by_fill, 0),
              "área de Δ")
        if fill:
            close(self, total.fill_m3, float(by_fill.cut_m3[1]), "relleno")
            close(self, total.area_m2(filled), moved_area(by_fill, 1), "área del relleno")
            outside = by_fill.outside
            close(self, total.unsplit_m3, float(by_fill.cut_m3[outside]), "desdoblado")
            close(self, total.area_m2(unsplit), moved_area(by_fill, outside),
                  "área del desdoblado")
        by_sector = cubication(sources["exploitation"], sources["final"], e,
                               domains("Sectores", sectors))
        dug = cubication(sources["start"], sources["exploitation"], e,
                         domains("Sectores", sectors))
        self.assertEqual(float(dug.fill_m3[0]), 0.0)
        close(self, total.exp_cut_m3, float(dug.cut_m3[0]), "excavación")
        close(self, total.exp_cut_area_m2, moved_area(dug, 0), "área de la excavación")
        for row, code in enumerate(sectors, start=1):
            item = found.sector(code)
            close(self, item.unsplit_m3 + item.fill_m3, float(by_sector.cut_m3[row]),
                  f"Δ de {code}")
            close(self, item.area_m2(unsplit) + item.area_m2(filled),
                  moved_area(by_sector, row), f"área de Δ de {code}")
            close(self, item.exp_cut_m3, float(dug.cut_m3[row]), f"excavación de {code}")
            close(self, item.exp_cut_area_m2, moved_area(dug, row),
                  f"área de la excavación de {code}")


SYNTH = gis_grid.Grid(qfx.BASE[0], qfx.BASE[1] + 96.0, 2.0, 2.0, 36, 48)
"""Una rejilla sintética de 48 × 36 celdas de 2 m."""
SYNTH_E = 0.25
SYNTH_FILL = {"relleno": ((6, 16), (5, 25))}
SYNTH_SECTORS = {"sector_1": ((0, 40), (0, 18)), "sector_2": ((0, 40), (18, 36))}
"""Rectángulos de filas × columnas; las filas 40 a 47, de ningún sector."""


def synthetic() -> dict[str, Any]:
    """Una cantera sintética con las dos superficies ya ordenadas: el dominio, un rectángulo con
    un hueco; ``Δ`` en múltiplos de 1/16 m con muchas celdas en 0 y en ``e`` exactos (empates de
    la regla) y una celda sin final dentro del dominio; fuera, las dos son el terreno (y una
    celda sin terreno)."""
    rng = np.random.default_rng(14017)
    rows, cols = np.indices(SYNTH.shape)
    terrain = 200.0 + 0.5 * cols + 0.25 * rows + rng.integers(0, 48, SYNTH.shape) / 16.0
    terrain[0, 0] = NAN
    domain = (rows >= 4) & (rows < 44) & (cols >= 3) & (cols < 33)
    domain &= ~((rows >= 20) & (rows < 26) & (cols >= 10) & (cols < 16))
    dug = rng.integers(0, 129, SYNTH.shape) / 16.0
    exploitation = np.where(domain, terrain - dug, terrain)
    kind = rng.integers(0, 4, SYNTH.shape)
    split = np.select([kind == 0, kind == 1, kind == 2],
                      [0.0, SYNTH_E, 0.125], rng.integers(1, 97, SYNTH.shape) / 16.0)
    final = np.where(domain, exploitation - split, exploitation)
    final[30, 30] = NAN
    labels = np.zeros(SYNTH.shape, np.int16)
    fill = np.zeros(SYNTH.shape, bool)
    for index, (row_range, col_range) in enumerate(SYNTH_SECTORS.values(), start=1):
        labels[slice(*row_range), slice(*col_range)] = index
    for row_range, col_range in SYNTH_FILL.values():
        fill[slice(*row_range), slice(*col_range)] = True
    return {"terrain": terrain, "exploitation": exploitation, "final": final, "fill": fill,
            "domain": seeds_mod.domain_of(domain, labels, SECTORS, SYNTH.cell_area)}


@contextmanager
def written(grids: dict[str, np.ndarray], geometry: Any) -> Iterator[dict[str, Any]]:
    """Las rejillas ``grids`` escritas como GeoTIFF en una carpeta temporal: sus fuentes de la
    011 por nombre."""
    with project_tmp("gb-t17-") as folder:
        yield {name: write_grid(folder / f"{name}.tif", values, geometry)
               for name, values in grids.items()}


class SyntheticReservesTest(ReservesMixin, unittest.TestCase):
    """RF-014-15: los volúmenes de la clasificación, iguales a los de la cubicación de la 011 a
    ≤ 10⁻⁶ relativo, en total, por clase y por sector, en una rejilla sintética con empates."""

    def test_the_classes_match_the_011(self) -> None:
        data = synthetic()
        found = last_result(quarry.classify_steps(
            data["final"], data["exploitation"], data["terrain"], data["domain"], SYNTH, SYNTH_E,
            fill_zones=data["fill"]))
        delta = data["exploitation"] - data["final"]
        inside = data["domain"].mask & np.isfinite(delta)
        self.assertGreater(int(np.count_nonzero(inside & (delta == SYNTH_E))), 100)
        self.assertGreater(found.total.cells_of(CellClass.FILL), 30)
        self.assertGreater(found.total.cells_of(CellClass.UNSPLIT), 150)
        self.assertEqual(found.total.nodata_cells, 1)
        with written({"start": data["terrain"], "exploitation": data["exploitation"],
                      "final": data["final"]}, SYNTH) as sources:
            self.compare_with_the_011(
                found, sources,
                {name: cell_box(SYNTH, *box) for name, box in SYNTH_FILL.items()},
                {code: cell_box(SYNTH, *box) for code, box in SYNTH_SECTORS.items()})


# --- En la cantera -------------------------------------------------------------------------------

RING_CELLS = 3
CONSERVE_SLOPE_DEG = 35.0
"""El talud de conservación de la prueba (D-9: un dato de entrada, el del análisis)."""
MIN_THICKNESS_M = 0.02
EXPL = qfx.EXPLOITATION_PROFILE
REST = qfx.FINAL_PROFILE
CORRIDOR = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                gradient_field="pendiente")


def profile_values() -> dict[str, object]:
    """Los parámetros de los dos perfiles de la cantera (clave → valor)."""
    params = import_geoblender("design.params")
    found: dict[str, object] = {}
    for profile in (EXPL, REST):
        for param, value in (("height_m", profile.height_m), ("face_deg", profile.face_deg),
                             ("berm_m", profile.berm_m), ("anchor_m", profile.anchor_m),
                             ("mesh_factor", profile.mesh_factor)):
            found[params.bench_key(profile.code, param)] = value
    return found


def local_box(box: tuple[float, float, float, float]) -> np.ndarray:
    """El rectángulo local ``box`` en absolutas."""
    x0, y0 = qfx.BASE
    west, south, east, north = box
    return np.array([[x0 + west, y0 + south], [x0 + east, y0 + south], [x0 + east, y0 + north],
                     [x0 + west, y0 + north]])


class QuarryClassesTest(ReservesMixin, qfx.QuarryProjectCase):
    """RF-014-15 y RF-014-16 en la cantera: ``quarry_steps`` clasifica sus dos superficies con la
    capa de zonas de restauración por relleno. E3 (la final ``REST_5_35_6`` y la explotación
    ``EXPL_10_60_6``, «final primero») deja poco desdoblado y ningún relleno; con los perfiles al
    revés, la explotación queda muy por encima de la final y hay desdoblado y relleno."""

    e3: ClassVar[Any]
    swapped: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        access = import_geoblender("gis.masks.access")
        gstore = import_geoblender("gis.store")
        masks = access.load_masks(cls.project, cls.v1.uid)
        refs, labels = seeds_mod.sector_layout(cls.project, masks)
        cls.geometry = masks.grid
        cls.start = qfx.terrain()
        area = quarry.excavation_area(masks, cls.start)
        cls.domain = seeds_mod.domain_of(area, labels, refs, cls.geometry.cell_area)
        with cls.project.read() as conn:
            floors_layer = gstore.read_features(conn, qfx.FLOORS_LAYER)
            corridors_layer = gstore.read_features(conn, qfx.CORRIDORS_LAYER)
        floors = quarry.join_floors(
            quarry.floor_map(floors_layer, model.LayerField(qfx.FLOORS_LAYER, "cota"),
                             cls.start, cls.geometry),
            quarry.corridor_cells(corridors_layer, CORRIDOR, cls.geometry))
        zone = quarry.ConserveZone("Ladera a conservar", qfx.in_box(qfx.CONSERVE_LOCAL))
        ceiling = last_result(quarry.conservation_ceiling_steps(
            (zone,), cls.start, cls.geometry, CONSERVE_SLOPE_DEG))
        cls.fill = zones.layer_cells(cls.project, qfx.FILL_LAYER, cls.geometry)
        common = {"start": cls.start, "masks": masks, "domain": cls.domain,
                  "values": profile_values(), "ring_cells": RING_CELLS,
                  "min_thickness_m": MIN_THICKNESS_M, "face_tolerance_deg": 1.0,
                  "warning_ratio": 2.0, "floors": floors, "ceiling": ceiling,
                  "fill_zones": cls.fill}
        outcomes = []
        for name, final, exploitation in (("Cantera E3", REST, EXPL),
                                          ("Cantera al revés", EXPL, REST)):
            request = model.QuarryRequest(
                name=name, start=qfx.START_DATASET,
                final=model.QuarrySide(base_profile=final.code),
                exploitation=model.QuarrySide(base_profile=exploitation.code,
                                              anchor="nearest_floor"),
                floors=model.LayerField(qfx.FLOORS_LAYER, "cota"),
                conserve=(model.Zone("layer", qfx.CONSERVE_LAYER),), corridors=CORRIDOR,
                fill_zones=qfx.FILL_LAYER)
            steps = list(quarry.quarry_steps(quarry.QuarryJob(request=request, **common)))
            outcomes.append((steps, steps[-1].result))
        (cls.e3_steps, cls.e3), (_steps, cls.swapped) = outcomes
        cls.sources = cls.enterClassContext(written({
            "start": cls.start, "e3_exploitation": cls.e3.exploitation_grid,
            "e3_final": cls.e3.final_grid, "swapped_exploitation": cls.swapped.exploitation_grid,
            "swapped_final": cls.swapped.final_grid}, cls.geometry))

    def sources_of(self, prefix: str) -> dict[str, Any]:
        return {"start": self.sources["start"],
                "exploitation": self.sources[f"{prefix}_exploitation"],
                "final": self.sources[f"{prefix}_final"]}

    def test_the_fill_layer_gives_the_fill_zone(self) -> None:
        """La capa de zonas de restauración por relleno (D-11) de la cantera: 3.000 celdas."""
        np.testing.assert_array_equal(self.fill, qfx.in_box(qfx.FILL_ZONE_LOCAL))
        self.assertEqual(int(np.count_nonzero(self.fill)), 3_000)

    def test_quarry_steps_classifies_its_two_surfaces(self) -> None:
        """RF-014-15: ``quarry_steps`` clasifica las dos superficies ya ordenadas (las de
        ``final_grid`` y ``exploitation_grid``) con el espesor mínimo y las zonas de relleno del
        trabajo, en un paso ``classes`` antes del último; la clase de cada celda es la de la regla
        y fuera del recinto no hay clase."""
        self.assertIn("classes", {step.phase for step in self.e3_steps})
        for outcome in (self.e3, self.swapped):
            again = last_result(quarry.classify_steps(
                outcome.final_grid, outcome.exploitation_grid, self.start, self.domain,
                self.geometry, MIN_THICKNESS_M, fill_zones=self.fill))
            np.testing.assert_array_equal(outcome.classes.grid, again.grid)
            self.assertEqual(outcome.classes.total, again.total)
            self.assertEqual(outcome.classes.sectors, again.sectors)
            delta = outcome.exploitation_grid - outcome.final_grid
            inside = self.domain.mask
            expected = np.where(delta > MIN_THICKNESS_M, np.where(self.fill, 2.0, 1.0), 0.0)
            np.testing.assert_array_equal(outcome.classes.grid[inside], expected[inside])
            self.assertTrue(bool(np.all(np.isnan(outcome.classes.grid[~inside]))))

    def test_e3_has_unsplit_and_no_fill(self) -> None:
        """E3 con «final primero»: la explotación sube a la final casi en todo el recinto; queda
        desdoblado donde la explotación, con sus bancos de 10 m, deja una cresta sobre la final, y
        ninguno en la zona de relleno (junto a la coronación, donde las dos son la misma)."""
        total = self.e3.classes.total
        self.assertGreater(total.cells_of(CellClass.UNSPLIT), 0)
        self.assertEqual(total.cells_of(CellClass.FILL), 0)
        self.assertEqual(total.cells, self.domain.cells)
        self.assertEqual(total.nodata_cells, 0)

    def test_e3_matches_the_011(self) -> None:
        """RF-014-15: los volúmenes de E3, iguales a los de la cubicación de la 011 sobre las
        mismas rejillas a ≤ 10⁻⁶ relativo, en total y en los dos sectores."""
        self.compare_with_the_011(
            self.e3.classes, self.sources_of("e3"),
            {"relleno": local_box(qfx.FILL_ZONE_LOCAL)},
            {sector.code: local_box(qfx.SECTORS_LOCAL[sector.name])
             for sector in self.domain.sectors})

    def test_unsplit_and_fill_match_the_011(self) -> None:
        """RF-014-15 con desdoblado y relleno (los perfiles al revés): toda la zona de relleno es
        relleno y lo demás que se mueve, desdoblado; sus volúmenes y áreas, los de la 011 con la
        zona de relleno y con los sectores como dominios, a ≤ 10⁻⁶ relativo."""
        found = self.swapped.classes
        self.assertEqual(found.total.cells_of(CellClass.FILL), 3_000)
        self.assertGreater(found.total.cells_of(CellClass.UNSPLIT), 10_000)
        self.compare_with_the_011(
            found, self.sources_of("swapped"),
            {"relleno": local_box(qfx.FILL_ZONE_LOCAL)},
            {sector.code: local_box(qfx.SECTORS_LOCAL[sector.name])
             for sector in self.domain.sectors})

    def test_the_outcome_carries_its_figures(self) -> None:
        """RF-014-16: el resultado lleva las cifras CALCULADO de la clasificación con el nombre
        de la cantera, en total y por sector (las de ``classification_figures``), y el mensaje
        dice el desdoblado y el relleno."""
        for outcome, name in ((self.e3, "Cantera E3"), (self.swapped, "Cantera al revés")):
            expected = quarry.classification_figures(name, outcome.classes)
            self.assertEqual(outcome.figures, expected)
            sectors = {item.scope.get("sector") for item in outcome.figures}
            self.assertEqual(sectors, {None, "sector_1", "sector_2"})
            self.assertIn("desdoblado", outcome.message)
            self.assertIn("relleno de restauración", outcome.message)

    def test_quarry_steps_checks_the_fill_zones(self) -> None:
        """Error del programa al llamar: unas zonas de relleno que no son de la rejilla."""
        job = quarry.QuarryJob(
            request=self.e3_request(), start=self.start, masks=self.masks(), domain=self.domain,
            values=profile_values(), ring_cells=RING_CELLS, min_thickness_m=MIN_THICKNESS_M,
            face_tolerance_deg=1.0, warning_ratio=2.0, fill_zones=self.fill[:10])
        with self.assertRaises(ValueError):
            quarry.quarry_steps(job)

    def e3_request(self) -> Any:
        return model.QuarryRequest(name="Cantera E3", start=qfx.START_DATASET,
                                   final=model.QuarrySide(base_profile=REST.code),
                                   exploitation=model.QuarrySide(base_profile=EXPL.code))


if __name__ == "__main__":
    unittest.main()
