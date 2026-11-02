# SPDX-License-Identifier: GPL-3.0-or-later
"""Semillas, dominio de trabajo y vista previa (spec 013, T04; HU-013-1; RF-013-01, RF-013-02,
RF-013-03; CE-013-07; plan 013 §5.3.1, D-15, D-16).

- **Semillas** (RF-013-01): la rejilla de semillas sale de una superficie del proyecto o de la
  versión en una zona (el dominio por defecto, la zona de una restricción, un sector o una capa de
  polígonos), de una cota fija en las celdas de una zona o de una rejilla de cotas; la cota donde
  manda y ``+inf`` en las demás; con su número de celdas, su área, sus cotas mínima y máxima. Se
  compara con el cálculo independiente de las máscaras, de los sectores y de la superficie en
  numpy. Ninguna entrada se modifica ni se remuestrea.
- **Dominio de trabajo** (RF-013-02): el dominio por defecto de las máscaras y la franja de solo
  relleno, acotable a sectores o a una capa de polígonos, y nunca ampliado; los sectores que
  toca (D-15: los que tienen alguna celda en él) y las celdas que no son de ninguno.
- **Ninguna semilla se descarta en silencio** (CE-013-07; errores 10, 17, 56 y 66): las semillas
  «en toda la ladera» se conservan todas y se cuentan las que quedan fuera del dominio (con su
  área) y las celdas de la zona sin cota; la vista previa lo dice con el número y avisa.
- **Vista previa** (RF-013-03): el resumen —semillas, dominio, porcentaje con semilla, sectores
  que toca con su estado, estado de las máscaras— en los dos idiomas, sin escribir nada en el
  proyecto y sin compilar las máscaras que faltan.
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

seeds = import_geoblender("design.seeds")
preview = import_geoblender("design.preview")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
zones = import_geoblender("design.zones")
surfaces = import_geoblender("design.surfaces")
access = import_geoblender("gis.masks.access")
i18n = import_geoblender("core.i18n")

GRID = cfx.SITE_GRID
CELL_M2 = 4.0
ROWS, COLS = np.indices(GRID.shape)
SLOPE = 600.0 + 0.5 * COLS + 0.25 * ROWS  # exacta en binario
"""La ladera: sube al este y al sur, sin huecos."""
HOLES = SLOPE.copy()
HOLES[(ROWS % 5 == 0) & (COLS % 5 == 0)] = np.nan
HOLES[0, 0] = np.inf
HOLES[1, 1] = -np.inf
"""La ladera con huecos: 1.023 celdas NaN y dos infinitas (1.025 sin cota finita)."""
NON_FINITE = 1025
ISLAND = np.full(GRID.shape, np.nan)
ISLAND[:10, :10] = 650.0
"""Una superficie con cota solo en un bloque de 10 × 10 celdas al noroeste (el lector rechaza una
superficie entera sin dato)."""

LAYER = "gis_fea_cuadro"  # 10 × 10 celdas dentro del sector 1 y del dominio
STRADDLE = "gis_fea_a_caballo"  # cruza el límite legal: dominio y franja
BETWEEN = "gis_fea_entre_sectores"  # cruza los dos sectores y el hueco entre ellos
BIG = "gis_fea_todo"  # cubre toda la rejilla y más
FAR = "gis_fea_lejos"  # dentro de la rejilla pero fuera del perímetro de actuación
LINES = "gis_fea_lineas"  # una capa de líneas: no es de polígonos


def grouped(number: int) -> str:
    """Un entero como lo escribe el español de Geoblender: espacio fino de miles."""
    return f"{number:,}".replace(",", i18n.THIN_SPACE)


def finish(steps: Any) -> tuple[list[Any], Any]:
    """Los ``Progress`` de unos pasos (menos el último) y el resultado del último."""
    found = list(steps)
    return found[:-1], found[-1].result


def request(source: Any, domain: Any = None) -> Any:
    """Una petición de envolvente con unas semillas y un acotado (lo demás no importa aquí)."""
    return model.EnvelopeRequest("e1", "down", source, slope_deg=35.0,
                                 domain=model.WorkDomain() if domain is None else domain)


def fixed(zone: Any, elevation: float = 700.0) -> Any:
    return model.SeedSource("fixed", zone=zone, elevation_m=elevation)


def from_surface(name: str, zone: Any = None) -> Any:
    return model.SeedSource("surface", surface=name, zone=zone)


def zone(kind: str, name: str | None = None) -> Any:
    return model.Zone(kind, name)


# --- Sin proyecto: los números de la ladera y los contadores -----------------------------------


class SeedCountsTest(unittest.TestCase):
    def test_every_seed_of_the_whole_slope_is_kept_and_those_outside_are_counted(self) -> None:
        """CE-013-07, RF-013-01, RF-013-03 (errores 10, 17, 56 y 66): con las semillas «en toda la
        ladera» de ``hillside_case`` (6.000 celdas de 2 m, de las que 2.000 quedan fuera del
        dominio de 80 × 80 celdas), ninguna se descarta: el conjunto las trae las 6.000 con su cota,
        y las 2.000 de fuera se cuentan con su área; las cotas, a mano (140,5 y 199,5 m)."""
        hill = dfx.hillside_case()
        domain = seeds.domain_of(hill.domain(), np.zeros(hill.grid.shape, np.int16), (),
                                 hill.grid.cell_area)
        found = seeds.collect_seeds(hill.seeds(), np.isfinite(hill.seeds()), domain, hill.grid)
        self.assertEqual((found.cells, found.outside_domain),
                         (hill.seed_cells, hill.outside_domain))
        self.assertEqual((found.cells, found.outside_domain), (6000, 2000))
        self.assertEqual((found.area_m2, found.outside_area_m2), (24_000.0, 8_000.0))
        self.assertEqual((found.min_m, found.max_m), (140.5, 199.5))
        self.assertEqual(found.nodata_cells, 0)
        self.assertEqual(domain.cells, 6400)
        np.testing.assert_array_equal(found.grid, hill.seeds())  # ni una cota cambia ni se quita
        self.assertEqual(int(np.isfinite(found.grid).sum()), found.cells)
        inside = int((np.isfinite(found.grid) & domain.mask).sum())
        self.assertEqual(inside + found.outside_domain, found.cells)
        self.assertEqual(inside, hill.inside_domain)

    def test_cells_of_the_zone_without_a_finite_elevation_are_counted(self) -> None:
        """RF-013-01 (nada se descarta en silencio): en una zona, la celda con NaN o ±inf no es
        semilla pero se cuenta aparte, así que la zona suma semillas más celdas sin cota; las
        entradas no se modifican y el resultado es un array nuevo."""
        grid = dfx.grid_from(6, 8, 2.0)
        values = np.arange(48, dtype=np.float64).reshape(6, 8) + 100.0
        values[1, 2], values[3, 4], values[3, 5] = np.nan, np.inf, -np.inf
        in_zone = np.zeros(grid.shape, dtype=bool)
        in_zone[1:5, 1:7] = True  # 24 celdas; tres sin cota finita
        domain = seeds.domain_of(np.ones(grid.shape, dtype=bool), np.zeros(grid.shape, np.int16),
                                 (), grid.cell_area)
        values_before, zone_before = values.copy(), in_zone.copy()
        found = seeds.collect_seeds(values, in_zone, domain, grid)
        self.assertEqual((found.cells, found.nodata_cells), (21, 3))
        self.assertEqual(found.cells + found.nodata_cells, int(in_zone.sum()))
        self.assertEqual(found.area_m2, 21 * 4.0)
        expected = np.where(in_zone & np.isfinite(values), values, np.inf)
        np.testing.assert_array_equal(found.grid, expected)
        np.testing.assert_array_equal(values, values_before)
        np.testing.assert_array_equal(in_zone, zone_before)
        self.assertFalse(np.shares_memory(found.grid, values))
        self.assertEqual((found.min_m, found.max_m), (float(expected[np.isfinite(expected)].min()),
                                                      float(expected[np.isfinite(expected)].max())))

    def test_no_seed_at_all_is_an_empty_set_not_an_error(self) -> None:
        """RF-013-03: sin ninguna celda con cota la vista previa tiene que poder decirlo (el
        rechazo de calcular es de RF-013-16): 0 celdas, sin cotas mínima ni máxima y todo
        ``+inf``."""
        grid = dfx.grid_from(4, 5, 1.0)
        domain = seeds.domain_of(np.ones(grid.shape, dtype=bool), np.zeros(grid.shape, np.int16),
                                 (), grid.cell_area)
        found = seeds.collect_seeds(np.full(grid.shape, np.nan), None, domain, grid)
        self.assertEqual((found.cells, found.area_m2, found.min_m, found.max_m),
                         (0, 0.0, None, None))
        self.assertEqual((found.outside_domain, found.nodata_cells), (0, 20))
        self.assertTrue(np.all(np.isposinf(found.grid)))

    def test_domain_counts_the_sectors_it_touches_and_the_cells_without_sector(self) -> None:
        """RF-013-02, D-15: de un dominio, sus celdas y su área; los sectores que tocan (los que
        tienen alguna celda en él, en el orden de los sectores) y las celdas que no son de
        ninguno, con su área."""
        refs = (seeds.SectorRef("a", "Sector A"), seeds.SectorRef("b", "Sector B"),
                seeds.SectorRef("c", "Sector C"))
        labels = np.zeros((4, 6), dtype=np.int16)
        labels[:, :2], labels[:, 2:4], labels[:2, 4:] = 1, 2, 3
        mask = np.zeros((4, 6), dtype=bool)
        mask[:, 3:] = True  # toca el B (columna 3), el C (filas 0 y 1) y celdas sin sector
        domain = seeds.domain_of(mask, labels, refs, 9.0)
        self.assertEqual(domain.cells, 12)
        self.assertEqual(domain.area_m2, 108.0)
        self.assertEqual(domain.touched, (refs[1], refs[2]))
        self.assertEqual(domain.sectors, refs)
        self.assertEqual((domain.unassigned_cells, domain.unassigned_area_m2), (4, 36.0))
        none = seeds.domain_of(np.zeros((4, 6), dtype=bool), labels, refs, 9.0)
        self.assertEqual((none.cells, none.touched, none.unassigned_cells), (0, (), 0))
        with self.assertRaises(ValueError):  # una máscara de otra forma es un error del programa
            seeds.domain_of(np.zeros((3, 6), dtype=bool), labels, refs, 9.0)


# --- Con el proyecto del diseño ----------------------------------------------------------------


class ProjectSeedsTest(dfx.DesignProjectCase):
    """Sobre el proyecto del diseño (160 × 160 celdas de 2 m, V01 con las máscaras al día): una
    ladera con y sin huecos, una superficie en otra rejilla y capas de polígonos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        shifted = dfx.gis.Grid(GRID.west + 2.0, GRID.north, GRID.dx, GRID.dy, GRID.ncols,
                               GRID.nrows)
        helper = cls("test_zone_kinds_give_their_cells")  # las ayudas son de instancia
        helper.write_surfaces(("ladera", dfx.raster(GRID, SLOPE)),
                              ("huecos", dfx.raster(GRID, HOLES)),
                              ("desplazada", dfx.raster(shifted, SLOPE)),
                              ("isla", dfx.raster(GRID, ISLAND)))
        helper.write_layer(LAYER, [[[cfx.rectangle(40.0, 40.0, 60.0, 60.0)]]])
        helper.write_layer(STRADDLE, [[[cfx.rectangle(180.0, 60.0, 240.0, 120.0)]]])
        helper.write_layer(BETWEEN, [[[cfx.rectangle(60.0, 60.0, 140.0, 100.0)]]])
        helper.write_layer(BIG, [[[cfx.rectangle(-100.0, -200.0, 400.0, 400.0)]]])
        helper.write_layer(FAR, [[[cfx.rectangle(230.0, -90.0, 290.0, -40.0)]]])
        helper.write_layer(LINES, [[[cfx.absolute([(50.0, 50.0), (90.0, 90.0)])]]], kind="line")
        # Las máscaras de V01, el dominio de trabajo y los sectores, una vez por clase: ninguna
        # prueba los modifica (una de ellas lo comprueba).
        cls.masks_ = helper.masks()
        cls.base = cls.masks_.default_domain() | cls.masks_.fill_strip()
        with cls.project.read() as conn:
            cls.sectors = import_geoblender("core.constraints.store").read_sectors(conn)
        cls.labels = zones.sector_labels(cls.sectors, GRID)

    # --- Ayudas ---------------------------------------------------------------------------

    def build(self, source: Any, domain: Any = None, **kwargs: Any) -> Any:
        """El ``SeedSet`` de unas semillas y un acotado sobre las máscaras de V01."""
        steps = seeds.build_seeds_steps(self.project, request(source, domain), self.masks_,
                                        **kwargs)
        return finish(steps)[1]

    def work_domain(self, domain: Any) -> Any:
        return finish(seeds.work_domain_steps(self.project, domain, self.masks_))[1]

    def layer_mask(self, name: str) -> np.ndarray:
        return zones.layer_cells(self.project, name, GRID)

    def snapshot(self) -> tuple[Any, ...]:
        """Lo que escribiría un cálculo: filas de operaciones, datos y cifras, y los ficheros."""
        counts = tuple(self.query(f"SELECT COUNT(*) FROM {table}")[0][0]
                       for table in ("gb_operation", "gb_dataset", "gb_operation_io",
                                     "gb_figure"))
        files = tuple(sorted((path.relative_to(self.root).as_posix(), path.stat().st_size)
                             for path in self.root.rglob("*") if path.is_file()))
        return counts, files

    # --- Las semillas (RF-013-01) ---------------------------------------------------------

    def test_zone_kinds_give_their_cells(self) -> None:
        """RF-013-01, D-16: la cota fija se pone en las celdas de la zona —el dominio por defecto
        de las máscaras, la zona de una restricción (la balsa: 60 × 50 m = 750 celdas), un sector
        (70 × 160 m = 2.800 celdas) o una capa de polígonos (20 × 20 m = 100 celdas)— y en ninguna
        más: la rejilla es la cota donde manda y ``+inf`` en las demás, con su recuento, su área y
        su cota."""
        cases = (
            (zone("domain"), self.masks_.default_domain(), None),
            (zone("constraint", "balsa"), self.masks_.zone("balsa").mask(GRID.shape), 750),
            (zone("sector", "sector_2"), self.labels == 2, 2800),
            (zone("layer", LAYER), self.layer_mask(LAYER), 100),
        )
        for where, expected, by_hand in cases:
            with self.subTest(zone=where.kind):
                found = self.build(fixed(where, 701.5))
                np.testing.assert_array_equal(found.grid, np.where(expected, 701.5, np.inf))
                self.assertEqual(found.grid.dtype, np.float64)
                self.assertEqual(found.grid.shape, GRID.shape)
                self.assertEqual(found.cells, int(expected.sum()))
                if by_hand is not None:
                    self.assertEqual(found.cells, by_hand)
                self.assertEqual(found.area_m2, found.cells * CELL_M2)
                self.assertEqual((found.min_m, found.max_m), (701.5, 701.5))
                self.assertEqual(found.nodata_cells, 0)
                self.assertTrue(found.geometry.same_geometry(GRID))

    def test_surface_seeds_are_the_cells_of_the_surface_in_the_zone(self) -> None:
        """RF-013-01: de una superficie con huecos (NaN e infinitos) en un sector, las semillas son
        las celdas del sector con cota finita, con su cota exacta, bit a bit (ni remuestreo ni
        interpolación); las del sector sin cota finita no son semilla pero se cuentan; ``+inf``
        fuera. El área y las cotas mínima y máxima salen de las semillas."""
        found = self.build(from_surface("gis_dtm_huecos", zone("sector", "sector_2")))
        in_zone = self.labels == 2
        chosen = in_zone & np.isfinite(HOLES)
        np.testing.assert_array_equal(found.grid[chosen], HOLES[chosen])
        self.assertTrue(np.all(np.isposinf(found.grid[~chosen])))
        self.assertEqual(found.cells, int(chosen.sum()))
        self.assertEqual(found.nodata_cells, int((in_zone & ~np.isfinite(HOLES)).sum()))
        self.assertGreater(found.nodata_cells, 0)
        self.assertEqual(found.cells + found.nodata_cells, 2800)
        self.assertEqual(found.area_m2, found.cells * CELL_M2)
        self.assertEqual((found.min_m, found.max_m), (float(HOLES[chosen].min()),
                                                     float(HOLES[chosen].max())))

    def test_the_surface_of_the_active_version_or_the_project_is_read(self) -> None:
        """RF-013-01: la superficie se pide por su nombre y se lee la de la versión activa o, si no
        tiene una así, la del proyecto (lo hace ``design.surfaces``); aquí, una del proyecto desde
        V01 da las mismas semillas que su lectura directa."""
        found = self.build(from_surface("gis_dtm_ladera", zone("layer", LAYER)))
        expected = self.layer_mask(LAYER)
        np.testing.assert_array_equal(found.grid, np.where(expected, SLOPE, np.inf))

    def test_a_grid_of_elevations_and_a_surface_without_zone_cover_the_whole_grid(self) -> None:
        """RF-013-01: una rejilla de cotas pone semilla en toda celda con cota finita (y, si se da
        una zona, solo en ella); una superficie sin zona es toda la superficie. Las celdas sin cota
        finita se cuentan, no desaparecen."""
        for source in (model.SeedSource("grid", grid="gis_dtm_huecos"),
                       from_surface("gis_dtm_huecos")):
            with self.subTest(kind=source.kind):
                found = self.build(source)
                self.assertEqual((found.cells, found.nodata_cells),
                                 (GRID.ncols * GRID.nrows - NON_FINITE, NON_FINITE))
                finite = np.isfinite(HOLES)
                np.testing.assert_array_equal(found.grid[finite], HOLES[finite])
        found = self.build(model.SeedSource("grid", grid="gis_dtm_huecos",
                                            zone=zone("layer", LAYER)))
        inside = self.layer_mask(LAYER)
        self.assertEqual(found.cells, int((inside & np.isfinite(HOLES)).sum()))
        self.assertEqual(found.cells + found.nodata_cells, 100)

    def test_the_whole_slope_keeps_every_seed_and_counts_those_outside_the_domain(self) -> None:
        """CE-013-07 (errores 10, 17, 56 y 66): sembrar toda la ladera con el proyecto real deja
        las 25.600 semillas, todas con su cota, y cuenta las que quedan fuera del dominio de
        trabajo (todas menos las celdas del dominio) con su área; las que quedan dentro más las de
        fuera son todas."""
        found = self.build(from_surface("gis_dtm_ladera"))
        np.testing.assert_array_equal(found.grid, SLOPE)
        domain_cells = int(self.base.sum())
        self.assertEqual(found.cells, 25_600)
        self.assertEqual(found.domain.cells, domain_cells)
        self.assertEqual(found.outside_domain, 25_600 - domain_cells)
        self.assertEqual(found.outside_area_m2, found.outside_domain * CELL_M2)
        inside = int((np.isfinite(found.grid) & found.domain.mask).sum())
        self.assertEqual(inside, domain_cells)
        self.assertEqual(inside + found.outside_domain, found.cells)

    def test_seeds_inside_the_domain_are_not_outside(self) -> None:
        """RF-013-03: las semillas del dominio por defecto están dentro del dominio de trabajo; las
        de una capa a caballo del límite legal están dentro si son del dominio o de la franja de
        solo relleno (que el dominio incluye) y fuera si son del intocable que la cruza; y las de un
        lugar de la rejilla fuera del perímetro, todas fuera, con su área."""
        self.assertEqual(self.build(fixed(zone("domain"))).outside_domain, 0)
        layer = self.layer_mask(STRADDLE)
        found = self.build(fixed(zone("layer", STRADDLE)))
        self.assertEqual(found.cells, int(layer.sum()))
        self.assertEqual(found.outside_domain, int((layer & ~self.base).sum()))
        self.assertGreater(found.outside_domain, 0, "la capa cruza un intocable")
        self.assertGreater(int((layer & self.masks_.fill_strip()).sum()), 0)
        self.assertEqual(found.cells - found.outside_domain, int((layer & self.base).sum()))
        far = self.build(fixed(zone("layer", FAR)))
        self.assertEqual((far.cells, far.outside_domain), (750, 750))
        self.assertEqual(far.outside_area_m2, 3000.0)

    def test_the_inputs_are_not_modified_and_the_result_does_not_alias_them(self) -> None:
        """RF-013-01 (regla 6): leer las semillas no cambia el fichero de la superficie ni las
        máscaras, y escribir en la rejilla de semillas no cambia la superficie ni las máscaras:
        el resultado es un array propio."""
        import hashlib

        path = self.root / "rasters" / "gis_dtm_ladera.tif"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        classes = self.masks_.classes.copy()
        found = self.build(from_surface("gis_dtm_ladera"))
        found.grid[:] = -1.0
        found.domain.mask[:] = False
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        np.testing.assert_array_equal(self.masks_.classes, classes)
        again = surfaces.read_surface(self.project, "gis_dtm_ladera")
        np.testing.assert_array_equal(again.values, SLOPE)
        np.testing.assert_array_equal(self.masks_.default_domain() | self.masks_.fill_strip(),
                                      self.base)

    def test_a_surface_in_another_grid_is_refused_before_anything_is_built(self) -> None:
        """RF-013-16 (como RF-011-03): unas semillas de una superficie o una rejilla en otra
        rejilla se rechazan con el objeto, el campo y el valor, y no se escribe nada."""
        before = self.snapshot()
        for source in (from_surface("gis_dtm_desplazada"),
                       model.SeedSource("grid", grid="gis_dtm_desplazada")):
            with self.subTest(kind=source.kind):
                with self.assertRaises(messages.DesignError) as caught:
                    self.build(source)
                self.assertEqual((caught.exception.code, caught.exception.field),
                                 ("des.surface_mismatch", "west"))
                self.assertIn("gis_dtm_desplazada", caught.exception.text)
        self.assertEqual(self.snapshot(), before)

    def test_incomplete_seeds_and_non_finite_elevations_are_refused(self) -> None:
        """RF-013-01, RF-013-16: unas semillas a medias —sin superficie, sin rejilla, sin cota o
        sin zona (la cota fija la necesita), o una zona sin su nombre— se rechazan con el campo que
        falta; una cota fija no finita, con su valor; ninguna se calcula con ellas."""
        cases = (
            (model.SeedSource("surface"), "surface"),
            (model.SeedSource("grid"), "grid"),
            (model.SeedSource("fixed", zone=zone("domain")), "elevation_m"),
            (model.SeedSource("fixed", elevation_m=700.0), "zone"),
            (fixed(zone("layer")), "zone"),
            (fixed(zone("constraint")), "zone"),
            (fixed(zone("sector")), "zone"),
        )
        for source, field in cases:
            with self.subTest(source=source.kind, field=field):
                with self.assertRaises(messages.DesignError) as caught:
                    self.build(source)
                self.assertEqual((caught.exception.code, caught.exception.field),
                                 ("des.seed_missing", field))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(elevation=value):
                with self.assertRaises(messages.DesignError) as caught:
                    self.build(fixed(zone("domain"), value))
                self.assertEqual(caught.exception.code, "des.seed_elevation")
                self.assertEqual(caught.exception.field, "elevation_m")
                self.assertIn(str(value), caught.exception.text)

    def test_unknown_zones_are_refused_naming_them(self) -> None:
        """RF-013-16: una restricción que no tiene zona (``des.zone_unknown``), un sector que no
        es de los del proyecto (``des.sector_unknown``, con los que hay) o una capa de líneas
        (``des.layer_not_polygons``) como zona se rechazan nombrándolos."""
        with self.assertRaises(messages.DesignError) as caught:
            self.build(fixed(zone("constraint", "no_hay")))
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("des.zone_unknown", "no_hay"))
        with self.assertRaises(messages.DesignError) as caught:
            self.build(fixed(zone("sector", "sector_9")))
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("des.sector_unknown", "sector_9"))
        self.assertIn("sector_1, sector_2", caught.exception.text)
        with self.assertRaises(messages.DesignError) as caught:
            self.build(fixed(zone("layer", LINES)))
        self.assertEqual(caught.exception.code, "des.layer_not_polygons")

    # --- El dominio de trabajo (RF-013-02) ------------------------------------------------

    def test_the_domain_is_the_default_domain_and_the_fill_only_strip(self) -> None:
        """RF-013-02, RF-013-13 de la 012: sin acotar, el dominio de trabajo es la unión del
        dominio por defecto (6.840 celdas) y la franja de solo relleno (1.700), que no se
        solapan; con su área, y sin tocar las máscaras."""
        classes = self.masks_.classes.copy()
        domain = self.work_domain(model.WorkDomain())
        np.testing.assert_array_equal(domain.mask, self.masks_.default_domain()
                                      | self.masks_.fill_strip())
        self.assertEqual(domain.cells, int(self.masks_.default_domain().sum())
                         + int(self.masks_.fill_strip().sum()))
        self.assertEqual((int(self.masks_.default_domain().sum()),
                          int(self.masks_.fill_strip().sum())), (6840, 1700))
        self.assertEqual(domain.cells, 8540)
        self.assertEqual(domain.area_m2, 8540 * CELL_M2)
        self.assertEqual(domain.mask.dtype, np.bool_)
        np.testing.assert_array_equal(self.masks_.classes, classes)

    def test_the_domain_can_be_bounded_to_sectors_or_a_layer_and_is_never_widened(self) -> None:
        """RF-013-02: acotar a unos sectores o a una capa deja la parte del dominio que cae en
        ellos (la intersección), con los dos acotados juntos la intersección de ambos; una capa
        que cubre toda la rejilla no lo amplía y una fuera del perímetro lo deja vacío (sin error:
        el rechazo de calcular es de RF-013-16); en ningún caso hay celdas fuera de las del
        dominio por defecto más la franja."""
        cases = (
            (model.WorkDomain(sectors=("sector_1",)), self.base & (self.labels == 1)),
            (model.WorkDomain(sectors=("sector_2", "sector_1")),
             self.base & ((self.labels == 1) | (self.labels == 2))),
            (model.WorkDomain(layer=LAYER), self.base & self.layer_mask(LAYER)),
            (model.WorkDomain(layer=STRADDLE), self.base & self.layer_mask(STRADDLE)),
            (model.WorkDomain(layer=BIG), self.base),
            (model.WorkDomain(layer=FAR), np.zeros(GRID.shape, dtype=bool)),
            (model.WorkDomain(sectors=("sector_1",), layer=BETWEEN),
             self.base & (self.labels == 1) & self.layer_mask(BETWEEN)),
        )
        for bound, expected in cases:
            with self.subTest(sectors=bound.sectors, layer=bound.layer):
                domain = self.work_domain(bound)
                np.testing.assert_array_equal(domain.mask, expected)
                self.assertEqual(domain.cells, int(expected.sum()))
                self.assertEqual(domain.area_m2, domain.cells * CELL_M2)
                self.assertFalse(np.any(domain.mask & ~self.base), "el dominio se amplió")
        self.assertEqual(self.work_domain(model.WorkDomain(sectors=("sector_1",))).cells, 2800)
        self.assertEqual(self.work_domain(model.WorkDomain(layer=LAYER)).cells, 100)
        self.assertEqual(self.work_domain(model.WorkDomain(layer=FAR)).cells, 0)
        strip = self.work_domain(model.WorkDomain(layer=STRADDLE)).mask & self.masks_.fill_strip()
        self.assertGreater(int(strip.sum()), 0, "la capa a caballo incluye franja de relleno")

    def test_a_bounded_domain_bounds_where_seeds_count_as_outside(self) -> None:
        """RF-013-02, RF-013-03: las semillas fuera del dominio ya acotado cuentan como fuera: las
        del dominio por defecto, con el dominio acotado al sector 1, son las de fuera del sector 1;
        y el conjunto lleva el dominio con el que se contó."""
        found = self.build(fixed(zone("domain")), model.WorkDomain(sectors=("sector_1",)))
        seeded = np.isfinite(found.grid)
        self.assertEqual(found.cells, 6840)
        self.assertEqual(found.outside_domain, int((seeded & ~found.domain.mask).sum()))
        self.assertEqual(found.outside_domain, 6840 - 2800)
        self.assertEqual(found.domain.cells, 2800)

    def test_unknown_sector_in_the_bound_is_refused_naming_the_known_ones(self) -> None:
        """RF-013-02, RF-013-16: acotar a un sector que no existe se rechaza con su código y los
        que hay, antes de calcular nada."""
        with self.assertRaises(messages.DesignError) as caught:
            self.work_domain(model.WorkDomain(sectors=("sector_1", "sector_7")))
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("des.sector_unknown", "sector_7"))
        self.assertIn("sector_1, sector_2", caught.exception.text)

    def test_touched_sectors_are_those_with_a_cell_in_the_work_domain(self) -> None:
        """D-15: el dominio toca los sectores que tienen alguna celda en él —no los que tocan solo
        el dominio por defecto—; acotarlo cambia cuáles; y las celdas del dominio que no son de
        ningún sector (la franja de relleno y los huecos entre ellos) se cuentan con su área."""
        full = self.work_domain(model.WorkDomain())
        self.assertEqual([item.code for item in full.touched], ["sector_1", "sector_2"])
        self.assertEqual([item.name for item in full.touched], ["Sector 1", "Sector 2"])
        self.assertEqual(full.sectors, full.touched)
        loose = int((full.mask & (self.labels == 0)).sum())
        self.assertEqual(full.unassigned_cells, loose)
        self.assertGreaterEqual(loose, 1700)  # al menos la franja de solo relleno
        self.assertEqual(full.unassigned_area_m2, loose * CELL_M2)
        np.testing.assert_array_equal(full.labels, self.labels)
        only_one = self.work_domain(model.WorkDomain(layer=LAYER))
        self.assertEqual([item.code for item in only_one.touched], ["sector_1"])
        self.assertEqual(only_one.sectors, full.sectors)
        self.assertEqual(only_one.unassigned_cells, 0)
        both = self.work_domain(model.WorkDomain(layer=BETWEEN))
        self.assertEqual([item.code for item in both.touched], ["sector_1", "sector_2"])
        self.assertGreater(both.unassigned_cells, 0)  # la franja entre los sectores
        none = self.work_domain(model.WorkDomain(layer=FAR))
        self.assertEqual((none.touched, none.unassigned_cells), ((), 0))

    # --- Los pasos ------------------------------------------------------------------------

    def test_the_steps_report_progress_and_end_with_the_result(self) -> None:
        """RF-013-03 (por pasos, con avance y cancelación): cada paso es un ``Progress`` con su
        fase, lo hecho y el total, que no baja; solo el último lleva el resultado, que es el
        ``SeedSet``; con un presupuesto nulo cada unidad es un paso, y con el de por defecto hay
        los mismos o menos."""
        source = from_surface("gis_dtm_ladera", zone("layer", LAYER))
        fine, result = finish(seeds.build_seeds_steps(self.project, request(source), self.masks_,
                                                      budget_s=0.0))
        every = list(seeds.build_seeds_steps(self.project, request(source), self.masks_))
        coarse, same = every[:-1], every[-1].result
        self.assertIsInstance(result, seeds.SeedSet)
        self.assertIsInstance(same, seeds.SeedSet)
        self.assertGreaterEqual(len(fine), 4)
        self.assertLessEqual(len(coarse), len(fine))
        for step in (*fine, *coarse):
            self.assertIsNone(step.result)
            self.assertLessEqual(step.done, step.total)
        self.assertEqual([step.done for step in fine], sorted(step.done for step in fine))
        self.assertEqual(every[-1].done, every[-1].total)
        np.testing.assert_array_equal(result.grid, same.grid)

    def test_closing_the_steps_in_the_middle_leaves_nothing(self) -> None:
        """RF-013-33 (cancelar): cerrar el generador a mitad no lanza nada y no deja nada en el
        proyecto; después, el cálculo vuelve a funcionar."""
        before = self.snapshot()
        steps = seeds.build_seeds_steps(self.project, request(from_surface("gis_dtm_ladera")),
                                        self.masks_, budget_s=0.0)
        next(steps)
        next(steps)
        steps.close()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.build(fixed(zone("layer", LAYER))).cells, 100)

    def test_building_seeds_writes_nothing_in_the_project(self) -> None:
        """RF-013-03: ni las semillas ni el dominio escriben en el proyecto (ni operación, ni
        dato, ni cifra, ni fichero nuevo) ni cambian el tamaño de ningún fichero."""
        before = self.snapshot()
        self.build(from_surface("gis_dtm_huecos", zone("sector", "sector_1")),
                   model.WorkDomain(layer=BETWEEN))
        self.build(model.SeedSource("grid", grid="gis_dtm_ladera"))
        self.assertEqual(self.snapshot(), before)

    # --- La vista previa (RF-013-03) ------------------------------------------------------

    def summarize(self, source: Any, domain: Any = None, *, version: Any = None,
                  project: Any = None, **kwargs: Any) -> Any:
        target = self.v1 if version is None else version
        steps = preview.summarize_steps(self.project if project is None else project,
                                        request(source, domain), target.uid, **kwargs)
        return finish(steps)[1]

    def test_the_summary_says_the_magnitudes_of_the_example(self) -> None:
        """RF-013-03, E5: la vista previa resume las semillas (celdas, área, cotas), el dominio
        (hectáreas, celdas, área, porcentaje con semilla), las celdas de semilla fuera del dominio
        y los sectores que toca, en español con coma decimal y espacio fino de miles, como el
        ejemplo de la spec; las cifras, a mano: 100 celdas = 400 m², 8.540 celdas = 3,4 ha."""
        summary = self.summarize(fixed(zone("layer", LAYER), 700.0))
        self.assertIs(summary.masks_state, access.MaskState.CURRENT)
        self.assertEqual(summary.version, "V01")
        lines = summary.lines("es")
        self.assertEqual(lines[0], "Semillas: 100 celdas (400 m²), cotas 700,0 a 700,0 m; dominio: "
                                   "3,4 ha; 0 celdas de semilla fuera del dominio.")
        self.assertEqual(lines[1], f"Dominio de trabajo: {grouped(8540)} celdas "
                                   f"({grouped(34_160)} m²), 1,2 % con semilla.")
        self.assertIn("Máscaras de V01: al día.", lines)
        self.assertIn("Sectores que toca el dominio de trabajo: Sector 1, Sector 2.", lines)
        self.assertEqual(summary.warnings("es"), ())
        self.assertAlmostEqual(summary.coverage_pct, 100.0 / 8540.0 * 100.0, places=12)
        self.assertEqual(summary.seeds.cells, 100)
        english = summary.lines("en")
        self.assertIn("Masks of V01: up to date.", english)
        self.assertEqual(english[0], "Seeds: 100 cells (400 m²), elevations 700.0 to 700.0 m; "
                                     "work domain: 3.4 ha; 0 seed cells outside the work domain.")
        self.assertEqual(english[1], "Work domain: 8,540 cells (34,160 m²), 1.2 % of it with a "
                                     "seed.")

    def test_the_whole_slope_is_flagged_with_the_number_of_cells_outside(self) -> None:
        """CE-013-07, RF-013-03 (errores 10, 17, 56 y 66): la vista previa de una semilla en toda
        la ladera dice cuántas celdas de semilla quedan fuera del dominio (las 17.060 que no son de
        las 8.540 del dominio) con su área y lo avisa, en los dos idiomas."""
        summary = self.summarize(from_surface("gis_dtm_ladera"))
        outside = 25_600 - 8540
        self.assertEqual(summary.seeds.outside_domain, outside)
        self.assertEqual(summary.coverage_pct, 100.0)
        self.assertIn(f"{grouped(outside)} celdas de semilla fuera del dominio.",
                      summary.lines("es")[0])
        self.assertIn(f"{outside:,} seed cells outside the work domain.", summary.lines("en")[0])
        self.assertIn("des.seeds_outside_domain", [notice.code for notice in summary.notices])
        (warning,) = summary.warnings("es")
        self.assertIn(f"{grouped(outside)} celdas de semilla ({grouped(outside * 4)} m²) están "
                      "fuera del dominio de trabajo", warning)
        self.assertIn("Revise la zona de las semillas", warning)
        (english,) = summary.warnings("en")
        self.assertIn(f"{outside:,} seed cells ({outside * 4:,} m²) are outside the work domain",
                      english)

    def test_cells_without_elevation_in_the_zone_are_warned(self) -> None:
        """RF-013-01, RF-013-03 (nada se descarta en silencio): las celdas de la zona de las
        semillas sin cota finita se avisan con su número y la superficie."""
        summary = self.summarize(from_surface("gis_dtm_huecos", zone("sector", "sector_1")))
        missing = summary.seeds.nodata_cells
        self.assertGreater(missing, 0)
        (warning,) = summary.warnings("es")
        self.assertIn(f"{grouped(missing)} celdas ({grouped(missing * 4)} m²) de la zona de las "
                      "semillas no tienen una cota finita en «gis_dtm_huecos»", warning)

    def test_no_seeds_and_an_empty_domain_are_warned_not_refused(self) -> None:
        """RF-013-03 (el rechazo de calcular es de RF-013-16): con el dominio vacío o sin ninguna
        celda con cota la vista previa lo dice con un aviso, no con un error; con unas semillas
        fuera de un dominio vacío, también las cuenta."""
        empty = self.summarize(fixed(zone("layer", FAR)), model.WorkDomain(layer=FAR))
        self.assertEqual((empty.seeds.cells, empty.seeds.domain.cells), (750, 0))
        codes = [notice.code for notice in empty.notices]
        self.assertIn("des.preview_domain_empty", codes)
        self.assertIn("des.seeds_outside_domain", codes)
        self.assertIsNone(empty.coverage_pct)
        self.assertIn("El dominio de trabajo está vacío", " ".join(empty.warnings("es")))
        blank = self.summarize(from_surface("gis_dtm_isla", zone("layer", LAYER)))
        self.assertEqual((blank.seeds.cells, blank.seeds.nodata_cells), (0, 100))
        self.assertIn("des.preview_seeds_none", [notice.code for notice in blank.notices])
        self.assertIn("Semillas: ninguna", " ".join(blank.warnings("es")))
        self.assertEqual(blank.coverage_pct, 0.0)

    def test_masks_not_compiled_are_said_and_not_compiled_by_the_preview(self) -> None:
        """RF-013-03, §8: con las máscaras sin compilar (V02) la vista previa lo dice —versión y
        orden que lo resuelve— y no puede dibujar el dominio ni las semillas; no compila nada ni
        escribe en el proyecto (compilar es una operación propia al calcular)."""
        before = self.snapshot()
        summary = self.summarize(from_surface("gis_dtm_no_existe"), version=self.v2)
        self.assertIs(summary.masks_state, access.MaskState.MISSING)
        self.assertEqual(summary.version, "V02")
        self.assertIsNone(summary.seeds)
        self.assertIsNone(summary.domain)
        self.assertIsNone(summary.masks)
        self.assertIsNone(summary.coverage_pct)
        (warning,) = summary.warnings("es")
        self.assertIn("Las máscaras de V02 no se han compilado", warning)
        self.assertIn("Restricciones…", warning)
        self.assertIn("The masks of V02 have not been compiled", summary.warnings("en")[0])
        self.assertEqual(self.snapshot(), before)

    def test_stale_masks_are_said(self) -> None:
        """RF-013-03, §8: con las máscaras obsoletas la vista previa lo dice (no las usa:
        RF-013-04); no compila nada."""
        with dfx.open_design_project("gb-sp-") as (project, _clock):
            masks = access.load_masks(project, self.v1.uid)
            with project.write_transaction() as conn:
                conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, "
                             "since) VALUES ('operation', ?, 'dataset_changed', ?, ?)",
                             (masks.operation_uid, "x" * 32, "2026-10-28T10:00:00Z"))
            summary = self.summarize(fixed(zone("domain")), project=project)
        self.assertIs(summary.masks_state, access.MaskState.STALE)
        self.assertIsNone(summary.seeds)
        (warning,) = summary.warnings("es")
        self.assertIn("Las máscaras de V01 están obsoletas", warning)
        self.assertEqual([notice.code for notice in summary.notices],
                         ["des.preview_masks_stale"])

    def test_a_pending_search_is_marked_on_the_sector_the_domain_touches(self) -> None:
        """RF-013-03, RF-013-06: los sectores que toca el dominio salen con el estado de su
        búsqueda: el sector 2, con la búsqueda de intocables pendiente, se marca y se avisa con la
        orden que la hace; el 1 no. Acotado al sector 1, el 2 sigue pendiente pero ya no lo
        toca y no se avisa."""
        with dfx.open_design_project("gb-sp-") as (project, _clock):
            with project.write_transaction() as conn:
                conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = ?",
                             ("sector_2",))
            summary = self.summarize(fixed(zone("domain")), project=project)
            bounded = self.summarize(fixed(zone("domain")), model.WorkDomain(sectors=("sector_1",)),
                                     project=project)
        self.assertEqual([(item.code, item.name, item.touched, item.pending)
                          for item in summary.sectors],
                         [("sector_1", "Sector 1", True, False),
                          ("sector_2", "Sector 2", True, True)])
        (warning,) = summary.warnings("es")
        self.assertIn("Sector «Sector 2»: búsqueda de intocables pendiente", warning)
        self.assertIn("Buscar elementos intocables por sector…", warning)
        self.assertIn("untouchables search pending", summary.warnings("en")[0])
        self.assertEqual([(item.code, item.touched, item.pending) for item in bounded.sectors],
                         [("sector_1", True, False), ("sector_2", False, True)])
        self.assertNotIn("des.preview_sector_pending", [notice.code for notice in bounded.notices])

    def test_cells_without_sector_are_a_note(self) -> None:
        """§8 (sectores con huecos entre ellos), RF-013-03: las celdas del dominio que no son de
        ningún sector usan el perfil base y se informan con su número y su área."""
        summary = self.summarize(fixed(zone("domain")))
        loose = summary.domain.unassigned_cells
        self.assertGreater(loose, 0)
        self.assertIn(f"{grouped(loose)} celdas del dominio de trabajo ({grouped(loose * 4)} m²) "
                      "no son de ningún sector; usan el perfil base.", summary.lines("es"))

    def test_the_summary_carries_what_the_view_draws(self) -> None:
        """RF-013-03: el resumen lleva lo que dibuja la vista (T25) sin volver a leer el proyecto:
        las máscaras (sus zonas y su leyenda), el conjunto de semillas con su dominio y los
        sectores con su estado; los pasos acaban con el resumen."""
        summary = self.summarize(fixed(zone("layer", LAYER)))
        self.assertIsInstance(summary, preview.PreviewSummary)
        self.assertIsInstance(summary.masks, access.MaskSet)
        self.assertIs(summary.domain, summary.seeds.domain)
        self.assertEqual(sorted(summary.masks.zones), sorted(self.masks_.zones))
        self.assertTrue(all(isinstance(item, preview.SectorStatus) for item in summary.sectors))
        self.assertTrue(all(isinstance(item, preview.Notice) for item in summary.notices))
        steps, result = finish(preview.summarize_steps(self.project, request(
            fixed(zone("layer", LAYER))), self.v1.uid, budget_s=0.0))
        self.assertGreaterEqual(len(steps), 4)
        self.assertEqual(result.seeds.cells, 100)

    def test_the_preview_writes_nothing_in_the_project(self) -> None:
        """RF-013-03: la vista previa no escribe en el proyecto —ni operaciones, ni datos, ni
        cifras, ni ficheros—, ni cuando todo va bien ni cuando se rechaza unas semillas."""
        before = self.snapshot()
        self.summarize(from_surface("gis_dtm_ladera"))
        with self.assertRaises(messages.DesignError):
            self.summarize(from_surface("gis_dtm_desplazada"))
        self.assertEqual(self.snapshot(), before)


# --- Los mensajes de la tarea ------------------------------------------------------------------


class MessagesTest(unittest.TestCase):
    ERRORS = ("des.seed_missing", "des.seed_elevation", "des.sector_unknown")
    NOTES = ("des.preview_seeds", "des.preview_domain", "des.preview_sectors",
             "des.preview_unassigned", "des.preview_masks_current")
    WARNINGS = ("des.preview_seeds_none", "des.preview_domain_empty", "des.seeds_outside_domain",
                "des.seeds_without_data", "des.preview_sector_pending",
                "des.preview_masks_missing", "des.preview_masks_stale")
    VALUES = {"kind": "fixed", "known": "sector_1, sector_2", "cells": "10", "area": "40",
              "low": "1,0", "high": "2,0", "hectares": "0,1", "outside": "0", "coverage": "1,0",
              "sectors": "Sector 1", "surface": "gis_dtm_x", "sector": "Sector 2",
              "version": "V01"}

    def test_codes_have_their_severity_and_both_languages_with_every_value_filled(self) -> None:
        """Principio 10: los códigos de la tarea tienen su gravedad (los errores se lanzan, los
        avisos y las notas se informan), su texto en español y en inglés, y rellenos con sus
        valores no dejan ni «?» ni «{…}»."""
        for severity, codes in (("error", self.ERRORS), ("note", self.NOTES),
                                ("warning", self.WARNINGS)):
            for code in codes:
                with self.subTest(code=code):
                    self.assertEqual(messages.MESSAGES[code].severity, severity)
                    for language in ("es", "en"):
                        text = messages.render(code, language=language, field="campo",
                                               value="v", **self.VALUES)
                        self.assertNotIn("{", text)
                        self.assertNotIn("?", text)
        for code in self.ERRORS:
            error = messages.DesignError(code, obj="Objeto", field="campo", value="v",
                                         **self.VALUES)
            self.assertEqual(error.code, code)
        for code in (*self.NOTES, *self.WARNINGS):
            with self.assertRaises(ValueError):  # no se lanza: se informa
                messages.DesignError(code, obj="Objeto", field="campo")


if __name__ == "__main__":
    unittest.main()
