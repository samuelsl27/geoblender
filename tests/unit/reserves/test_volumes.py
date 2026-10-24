# SPDX-License-Identifier: GPL-3.0-or-later
"""Los pasos de una cubicación (spec 011, T13; HU-011-1, HU-011-2, HU-011-3; RF-011-01,
RF-011-05, RF-011-10, RF-011-22, RF-011-25; RNF-011-04; plan 011 A10, A14, D-25, D-26, D-27,
D-34).

``reserves.volumes.volume_steps`` cubica **por pasos** sobre ficheros (los GeoTIFF del proyecto
o de una instantánea): comprueba las superficies (A1), valida y recorta los dominios, lee las
bandas de todas las superficies al paso y las suma al núcleo en **un solo cálculo** (RF-011-10),
escribe, si se pide, la rejilla de diferencias por teselas en su temporal con el hash de contenido
calculado por bandas (D-25) y da las tablas en formato largo (``reserves.table``, D-27), las
cifras de los totales y de los subtotales de **un** reparto (D-26) y el factor combinado
(``reserves.scale``, D-34). ``tonnage_outputs`` hace lo mismo con las toneladas desde la tabla de
volúmenes (D-16). Ningún paso pasa de su presupuesto y cerrar los pasos a mitad no deja nada
(RF-011-25).

Datos: la pirámide de 2 m (100 × 100 celdas) y la columna sintética de materiales (50 × 40) de
``tests/support/res_fixtures.py``, escritas como GeoTIFF del perfil ``project`` con teselas de 16 en
una carpeta temporal; las referencias son el núcleo llamado directamente con las mismas bandas
(bit a bit), las cifras analíticas y el lector ``gis.geotiff@1``.
"""

from __future__ import annotations

import math
import sqlite3
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of

volumes = import_geoblender("reserves.volumes")
table = import_geoblender("reserves.table")
scale = import_geoblender("reserves.scale")
kernel = import_geoblender("reserves.kernel")
polygons = import_geoblender("reserves.polygons")
surfaces = import_geoblender("reserves.surfaces")
slices_module = import_geoblender("reserves.slices")
tonnage = import_geoblender("reserves.tonnage")
materials = import_geoblender("reserves.materials")
res_params = import_geoblender("reserves.params")
res_messages = import_geoblender("reserves.messages")
gis = import_geoblender("gis")
writer = import_geoblender("gis.geotiff.writer")
gis_reader = import_geoblender("gis.geotiff.reader")
gis_content = import_geoblender("gis.content")
readers = import_geoblender("core.content.readers")
datasets_model = import_geoblender("core.datasets.model")
figures_module = import_geoblender("core.provenance.figures")

Slices = slices_module.Slices
SurfaceRef = surfaces.SurfaceRef

TILE = 16
"""Teselas de los GeoTIFF de las pruebas (las de la 006 son de 256)."""
BAND = 16
"""Filas de una banda en las pruebas: 7 bandas en la pirámide y 3 en la columna."""
BUDGET_S = 0.05
SLACK_S = 0.010
"""Lo que un paso puede pasar de su presupuesto («Hecho cuando» de la T13)."""
TINY_S = 1e-9
"""Un presupuesto que no da para más de una unidad de trabajo por paso."""
CLOSURE = 1e-9
"""Cierre de un reparto con su total y frente a las cifras analíticas (D-14 b)."""
NAME = "Mensual"
PYRAMID_SLICES = Slices(10.0, 600.0, None)
TOTAL_KEYS = ("res.cut_m3", "res.fill_m3", "res.net_m3", "res.area_m2", "res.nodata_area_m2",
              "res.still_area_m2")


def _write(path: Path, values: np.ndarray, grid: Any) -> Path:
    """``values`` como GeoTIFF del perfil ``project`` con teselas de :data:`TILE`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with mock.patch.object(writer, "TILE_SIZE", TILE):
        writer.write_geotiff(gis.Raster(grid, values, fx.CRS, fx.VERTICAL), path,
                             profile="project")
    return path


def _source(path: Path, name: str) -> Any:
    return surfaces.grid_source(path, name=name, crs=fx.CRS, vertical=fx.VERTICAL)


def _run(request: Any, sources: dict, **kw: Any) -> tuple[list[Any], Any]:
    """Recorre los pasos de ``request`` (por bandas de :data:`BAND` filas): los avances y el
    resultado del último."""
    kw.setdefault("band_rows", BAND)
    seen = list(volumes.volume_steps(request, sources, **kw))
    return seen, seen[-1].result


def _polygons(items: Any) -> tuple[Any, ...]:
    return tuple(polygons.Polygon(item.fid, item.value, item.rings) for item in items)


def _reference(grid: Any, start: np.ndarray, final: np.ndarray, *, slices: Any = None,
               domains: tuple = (), case: Any = None, presence: float = 0.0) -> Any:
    """El núcleo llamado directamente, por bandas de :data:`BAND` filas, con las aristas de los
    dominios y, con ``case``, las bases y los espesores de su columna."""
    units = 0 if case is None else len(case.units)
    accumulators = kernel.Accumulators(grid, slices=slices, domains=len(domains), units=units,
                                       presence_m=presence)
    for first in range(0, grid.nrows, BAND):
        rows = slice(first, min(first + BAND, grid.nrows))
        weights = polygons.weights(domains, None, grid, rows) if domains else None
        bases, thicknesses = ((), ()) if case is None else fx.column_layers(case, rows)
        kernel.band_step(accumulators, kernel.BandValues(
            first, start[rows], final[rows], bases=bases, thicknesses=thicknesses), weights)
    return accumulators.result()


def _figures(result: Any) -> dict[tuple[str, str], Any]:
    """Las cifras por (clave, ámbito en JSON canónico); el ámbito, válido para ``gb_figure``."""
    found = {(item.key, figures_module.scope_json(item.scope)): item for item in result.figures}
    if len(found) != len(result.figures):
        raise AssertionError("dos cifras con la misma clave y el mismo ámbito")
    return found


def _scope(**values: Any) -> str:
    return figures_module.scope_json({"cubication": NAME, **values})


def _parameters(case: Any) -> dict[str, float]:
    """La densidad, el K y los porcentajes (sintéticos de prueba) de la columna ``case``."""
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


class _Folder(unittest.TestCase):
    """Una carpeta temporal por clase, con una subcarpeta ``rasters`` para la rejilla."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = cls.enterClassContext(project_tmp("gb-011-t13-"))
        cls.rasters = cls.folder / "rasters"
        cls.rasters.mkdir()

    def difference(self, name: str = "res_dif_mensual_v01.tif") -> tuple[Path, Path]:
        """El destino de la rejilla de diferencias y su temporal (como ``gis.store``)."""
        path = self.rasters / name
        return path, path.with_name(path.name + ".tmp-0123abcd")

    def assertNothingLeft(self) -> None:
        self.assertEqual(sorted(item.name for item in self.rasters.iterdir()), [])


class PyramidTest(_Folder):
    """La pirámide (CE-011-01) con sus cuadrantes y rodajas de 10 m, sobre ficheros."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.pair = fx.pyramid(2.0)
        grid = cls.pair.grid
        cls.sources = {
            volumes.START: _source(_write(cls.folder / "partida.tif", cls.pair.start.values,
                                          grid), "Pirámide"),
            volumes.FINAL: _source(_write(cls.folder / "final.tif", cls.pair.final.values,
                                          grid), "Base"),
        }
        cls.quadrants = _polygons(fx.pyramid_quadrants())
        cls.domains = volumes.DomainLayer("Cuadrantes", fx.QUADRANT_FIELD, cls.quadrants)

    def request(self, **kw: Any) -> Any:
        kw.setdefault("domains", self.domains)
        kw.setdefault("slices", PYRAMID_SLICES)
        return volumes.VolumeRequest(NAME, SurfaceRef(dataset="partida"),
                                     SurfaceRef(dataset="final"), **kw)

    def tearDown(self) -> None:
        for item in self.rasters.iterdir():
            item.unlink()

    def test_one_pass_gives_the_tables_and_the_figures_of_one_breakdown(self) -> None:
        """RF-011-01, RF-011-07, RF-011-09, RF-011-10, RF-011-22 (D-26, D-27): un solo cálculo
        da el núcleo bit a bit (el de la T08 por las mismas bandas); la tabla en formato largo
        tiene el total y cada cuadrante con «Fuera de los dominios» (que cierran con el total
        ≤ 10⁻⁹) y las cinco rodajas de 10 m (cada una ≤ 0,1 % del total de su analítico); las
        cifras son los totales, los de cada dominio y los de cada rodaja (ningún cruce), con su
        ámbito y finitas; sin factor de escala, sin sus cifras y con su nota en la tabla."""
        progress, result = _run(self.request(), self.sources)
        edges = tuple(item.edges for item in polygons.domain_edges(self.quadrants,
                                                                    self.pair.grid))
        reference = _reference(self.pair.grid, self.pair.start.values, self.pair.final.values,
                               slices=PYRAMID_SLICES, domains=edges)
        for name in ("cut_m3", "fill_m3", "net_m3", "area_m2", "nodata_area_m2",
                     "still_area_m2", "bounds", "slice_cut_m3", "slice_fill_m3"):
            np.testing.assert_array_equal(getattr(result.kernel, name),
                                          getattr(reference, name), err_msg=name)
        volume = fx.pyramid_volume()
        self.assertLessEqual(abs(result.cut_m3 - volume), fx.PYRAMID_TOLERANCE * volume)
        self.assertEqual(result.domains, ("Noreste", "Noroeste", "Suroeste", "Sureste"))
        self.assertEqual([item.phase for item in progress][-1], "result")
        self.assertIn("desmonte", progress[-1].message)

        cut = table.filter_rows(result.rows, quantity="cut_m3", bench=None, unit=None)
        by_domain = {row.domain: row.value for row in cut}
        self.assertEqual(list(by_domain), ["*", *result.domains, ""])
        self.assertEqual(by_domain["*"], float(reference.cut_m3[kernel.ALL]))
        parts = math.fsum(value for domain, value in by_domain.items() if domain != "*")
        self.assertLessEqual(abs(parts - result.cut_m3), CLOSURE * result.cut_m3)
        benches = [row for row in table.filter_rows(result.rows, domain="*", unit=None,
                                                    quantity="cut_m3") if row.bench is not None]
        expected = fx.pyramid_slices(10.0)
        self.assertEqual([row.bench for row in benches], [(low, high) for low, high, _ in expected])
        for row, (_low, _high, value) in zip(benches, expected, strict=True):
            self.assertLessEqual(abs(row.value - value), fx.PYRAMID_TOLERANCE * volume)
        self.assertLessEqual(abs(math.fsum(row.value for row in benches) - result.cut_m3),
                             CLOSURE * result.cut_m3)
        for row in result.rows:
            self.assertTrue(row.value is None or math.isfinite(row.value), row)
        factor = table.filter_rows(result.rows, quantity="grid_scale_factor")
        self.assertEqual([(row.value, row.note) for row in factor],
                         [(None, "res.note_no_scale_factor")])

        found = _figures(result)
        expected_keys = {(key, _scope()) for key in TOTAL_KEYS}
        for value in result.domains:
            expected_keys |= {(key, _scope(domain=value)) for key in TOTAL_KEYS}
        expected_keys |= {(key, _scope(outside=volumes.OUTSIDE_SCOPE)) for key in TOTAL_KEYS}
        for low, _high, _value in expected:
            expected_keys |= {("res.cut_m3", _scope(bench=low)), ("res.fill_m3", _scope(bench=low))}
        self.assertEqual(set(found), expected_keys)
        for figure in result.figures:
            self.assertTrue(math.isfinite(figure.value), figure)
            self.assertEqual(figure.unit, "m3" if figure.key.endswith("_m3") else "m2")
        self.assertEqual(found[("res.cut_m3", _scope())].value, result.cut_m3)
        self.assertEqual(found[("res.cut_m3", _scope(domain="Noreste"))].value,
                         float(reference.cut_m3[1]))
        self.assertEqual(found[("res.cut_m3", _scope(bench=620.0))].value, benches[2].value)
        self.assertNothingLeft()

    def test_the_difference_grid_is_written_by_tiles_with_its_digest(self) -> None:
        """RF-011-05 (D-25): con la rejilla pedida, ``final − partida`` (sin dato donde falta
        una de las dos, también un infinito) se escribe por teselas (un paso por tesela y el del
        IFD) en su temporal, sin tocar el destino, y su hash de contenido, calculado por bandas
        mientras se cubica, es el que da su lector ``gis.geotiff@1`` al leer el fichero."""
        grid = self.pair.grid
        start = self.pair.start.values.copy()
        final = self.pair.final.values.copy()
        start[3, 5:9] = np.nan
        start[40, 41] = np.inf
        final[60:62, 10] = np.nan
        sources = {
            volumes.START: _source(_write(self.folder / "partida_huecos.tif", start, grid), "A"),
            volumes.FINAL: _source(_write(self.folder / "final_huecos.tif", final, grid), "B"),
        }
        path, temporary = self.difference()
        with mock.patch.object(writer, "TILE_SIZE", TILE):
            progress, result = _run(self.request(difference_grid=True), sources,
                                    budget_s=TINY_S, difference_path=path,
                                    difference_temporary=temporary)
        tiles = -(-grid.nrows // TILE) * -(-grid.ncols // TILE)
        self.assertEqual([item.phase for item in progress].count("grid"), tiles + 1)
        self.assertEqual(result.difference.path, temporary)
        self.assertTrue(temporary.is_file())
        self.assertFalse(path.exists())
        request = gis_content.GEOTIFF.request(gis_content.GEOTIFF.kinds[0],
                                              datasets_model.DATASET_DECLARATIONS,
                                              {"main": temporary})
        self.assertEqual(result.difference.digest,
                         readers.read_content(gis_content.GEOTIFF, request))
        written = gis_reader.read_geotiff(temporary).values
        valid = np.isfinite(start) & np.isfinite(final)
        np.testing.assert_array_equal(np.isnan(written), ~valid)
        self.assertEqual(written[valid].tobytes(), (final - start)[valid].tobytes())
        self.assertLess(float(np.min(written[valid])), 0.0)  # negativa en desmonte

    def test_no_step_takes_longer_than_its_budget(self) -> None:
        """RNF-011-04 (A10): con ``budget_s = 0,05``, ninguna llamada a los pasos (con
        dominios, rodajas y la rejilla de diferencias) pasa de 0,05 s + 10 ms."""
        path, temporary = self.difference()

        def longest() -> float:
            run = drive_steps(volumes.volume_steps(
                self.request(difference_grid=True), self.sources, budget_s=BUDGET_S,
                difference_path=path, difference_temporary=temporary, band_rows=BAND))
            temporary.unlink()
            self.assertIsNotNone(run.result)
            return run.longest_s

        self.assertLessEqual(least_of(longest, BUDGET_S + SLACK_S, max_attempts=3),
                             BUDGET_S + SLACK_S)

    def test_closing_or_failing_midway_leaves_nothing(self) -> None:
        """RF-011-25: cerrar los pasos (Esc) mientras se leen las bandas o a mitad de la
        rejilla, o un fallo después de escribirla, no deja ningún fichero (ni el temporal ni el
        destino); cerrarlos tras el resultado deja el temporal a quien lo recibe."""
        path, temporary = self.difference()
        request = self.request(difference_grid=True, point_scale=1.0)
        for phase, skip in (("bands", 3), ("grid", 4)):
            with self.subTest(fase=phase), mock.patch.object(writer, "TILE_SIZE", TILE):
                steps = volumes.volume_steps(request, self.sources, budget_s=TINY_S,
                                             difference_path=path,
                                             difference_temporary=temporary, band_rows=BAND)
                seen = 0
                for item in steps:
                    seen += item.phase == phase
                    if seen == skip:
                        break
                self.assertEqual(seen, skip)
                if phase == "grid":
                    self.assertTrue(temporary.is_file())
                steps.close()
                self.assertNothingLeft()
        with mock.patch.object(scale, "combined_factor", side_effect=RuntimeError("fallo")), \
                self.assertRaises(RuntimeError):
            _run(request, self.sources, difference_path=path, difference_temporary=temporary)
        self.assertNothingLeft()
        steps = volumes.volume_steps(request, self.sources, difference_path=path,
                                     difference_temporary=temporary, band_rows=BAND)
        for item in steps:
            if item.result is not None:
                break
        steps.close()
        self.assertTrue(temporary.is_file())

    def test_rejections_before_computing(self) -> None:
        """RF-011-03 (A1), RF-011-08 (A6) y §8 de la spec: otra rejilla, dominios que se solapan o
        ninguna celda común dentro del ámbito se rechazan con su error, sin escribir nada; la
        misma superficie de partida y final da ceros con el aviso ``res.same_surface``; una
        fuente que falta es un error del programa al llamar."""
        path, temporary = self.difference()
        half = gis.Grid(west=self.pair.grid.west, north=self.pair.grid.north, dx=1.0, dy=1.0,
                        ncols=200, nrows=200)
        other = _source(_write(self.folder / "fina.tif", np.full(half.shape, 600.0), half),
                        "Fina")
        square = np.array([[735_150.0, 4_434_150.0], [735_250.0, 4_434_150.0],
                           [735_250.0, 4_434_250.0], [735_150.0, 4_434_250.0]])
        overlapping = volumes.DomainLayer("Fases", "fase", (
            polygons.Polygon(1, "1", (square,)), polygons.Polygon(2, "2", (square + 10.0,))))
        far = (polygons.Polygon(1, "Ámbito", (square + 10_000.0,)),)
        cases = (
            ("res.surfaces_mismatch", {}, {**self.sources, volumes.FINAL: other}),
            ("res.domains_invalid", {"domains": overlapping}, self.sources),
            ("res.no_common_cells", {"domains": None, "scope": far}, self.sources),
        )
        for code, changes, sources in cases:
            request = self.request(difference_grid=True, **changes)
            with self.subTest(code=code), self.assertRaises(res_messages.ResError) as caught:
                _run(request, sources, difference_path=path, difference_temporary=temporary)
            self.assertEqual(caught.exception.code, code)
            self.assertNothingLeft()
        same = volumes.VolumeRequest(NAME, SurfaceRef(dataset="partida"),
                                     SurfaceRef(dataset="partida"))
        _progress, result = _run(same, {volumes.START: self.sources[volumes.START],
                                        volumes.FINAL: self.sources[volumes.START]})
        self.assertEqual([item.code for item in result.warnings], ["res.same_surface"])
        self.assertIn("Pirámide", result.warnings[0].text())
        self.assertEqual((result.cut_m3, result.fill_m3), (0.0, 0.0))
        with self.assertRaises(ValueError):
            volumes.volume_steps(self.request(), {volumes.START: self.sources[volumes.START]})

    def test_an_invalid_scope_is_refused_before_computing(self) -> None:
        """RF-011-01 (regresión de la T37): un ámbito de dos partes que se solapan (contaría dos
        veces el solape) o uno que se corta a sí mismo (pesos con signo y «sin celdas
        comunes») se rechazan con ``res.scope_invalid``, que nombra la capa, sin escribir nada;
        el mismo ámbito partido en dos que solo comparten un lado da las mismas cifras que el
        polígono entero (≤ 10⁻⁹)."""
        path, temporary = self.difference()
        west, south = 735_100.0, 4_434_100.0

        def rect(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
            return np.array([[west + x0, south + y0], [west + x1, south + y0],
                             [west + x1, south + y1], [west + x0, south + y1]])

        bowtie = np.array([[west, south], [west + 60, south + 60], [west + 60, south],
                           [west, south + 60]])
        for label, scope, text in (
                ("solape", (polygons.Polygon(1, "", (rect(0, 0, 60, 60),)),
                            polygons.Polygon(2, "", (rect(30, 30, 90, 90),))),
                 "los polígonos 1 y 2 se solapan en 900,00 m²"),
                ("pajarita", (polygons.Polygon(1, "", (bowtie,)),),
                 "el polígono 1 se corta a sí mismo")):
            request = self.request(domains=None, scope=scope, scope_layer="Ámbito",
                                   difference_grid=True)
            with self.subTest(label), self.assertRaises(res_messages.ResError) as caught:
                _run(request, self.sources, difference_path=path, difference_temporary=temporary)
            self.assertEqual(caught.exception.code, "res.scope_invalid")
            self.assertIn("La capa «Ámbito» no sirve de ámbito", str(caught.exception))
            self.assertIn(text, str(caught.exception))
            self.assertNothingLeft()
        whole = (polygons.Polygon(1, "", (rect(0, 0, 90, 60),)),)
        halves = (polygons.Polygon(1, "", (rect(0, 0, 45, 60),)),
                  polygons.Polygon(2, "", (rect(45, 0, 90, 60),)))
        _seen, one = _run(self.request(domains=None, scope=whole), self.sources)
        _seen, two = _run(self.request(domains=None, scope=halves), self.sources)
        self.assertGreater(one.cut_m3, 0.0)
        self.assertLessEqual(abs(two.cut_m3 - one.cut_m3), CLOSURE * one.cut_m3)
        self.assertEqual(two.kernel.area_m2[kernel.ALL], one.kernel.area_m2[kernel.ALL])


class ColumnTest(_Folder):
    """La columna sintética de materiales (CE-011-02, CE-011-03) sobre ficheros."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        case = cls.case = fx.material_column()
        cls.column = fx.domain_column(case)
        grid = case.grid

        def source(name: str, raster: Any) -> Any:
            return _source(_write(cls.folder / f"{name}.tif", raster.values, grid), name)

        cls.sources = {volumes.START: source("partida", case.start),
                       volumes.FINAL: source("final", case.final)}
        for unit in case.units:
            if unit.base is not None:
                cls.sources[volumes.base_role(unit.code)] = source(f"base_{unit.code}",
                                                                   unit.base)
            if unit.thickness is not None:
                cls.sources[volumes.thickness_role(unit.code)] = source(
                    f"espesor_{unit.code}", unit.thickness)
        cls.slices = Slices(5.0, 595.0, None)
        cls.result = _run(cls.request_for(cls.column, cls.slices), cls.sources)[1]

    @staticmethod
    def request_for(column: Any, slices: Any = None) -> Any:
        return volumes.VolumeRequest(NAME, SurfaceRef(dataset="partida"),
                                     SurfaceRef(dataset="final"), slices=slices, column=column,
                                     presence_m=fx.ANTHROPIC_PRESENCE_M)

    def test_units_in_the_same_pass(self) -> None:
        """RF-011-10, RF-011-12, RF-011-14, RF-011-22 (T09): las unidades salen del mismo
        cálculo, bit a bit las del núcleo por las mismas bandas y cada una su analítico
        (≤ 10⁻⁹); en la tabla, cada unidad en total y por rodaja (que cierran con ella), sus
        áreas de ausencia y de cruce; en las cifras, el volumen de cada unidad (sin cruces con
        las rodajas)."""
        result = self.result
        reference = _reference(self.case.grid, self.case.start.values, self.case.final.values,
                               slices=self.slices, case=self.case,
                               presence=fx.ANTHROPIC_PRESENCE_M)
        for name in ("cut_m3", "unit_volume_m3", "unit_absent_m2", "unit_crossed_m2",
                     "unit_slice_m3"):
            np.testing.assert_array_equal(getattr(result.kernel, name),
                                          getattr(reference, name), err_msg=name)
        found = _figures(result)
        for position, unit in enumerate(self.case.units):
            with self.subTest(unit=unit.code):
                rows = table.filter_rows(result.rows, domain="*", unit=unit.code,
                                         quantity="volume_m3")
                total = [row.value for row in rows if row.bench is None]
                self.assertEqual(total, [float(reference.unit_volume_m3[kernel.ALL, position])])
                self.assertLessEqual(abs(total[0] - unit.expected_m3),
                                     CLOSURE * unit.expected_m3)
                benches = math.fsum(row.value for row in rows if row.bench is not None)
                self.assertLessEqual(abs(benches - total[0]), CLOSURE * self.case.cut_m3)
                self.assertEqual(found[("res.unit_volume_m3", _scope(unit=unit.code))].value,
                                 total[0])
                self.assertEqual(len(table.filter_rows(
                    result.rows, domain="*", bench=None, unit=unit.code,
                    quantity="absent_area_m2")), 1)
        self.assertFalse(any("unit" in item.scope and "bench" in item.scope
                             for item in result.figures))

    def test_tonnage_from_the_volume_table(self) -> None:
        """RF-011-15, RF-011-16, RF-011-18, RF-011-22 (T10, D-16, CE-011-03): las toneladas salen
        de la tabla de volúmenes sin releer las superficies, bit a bit las de
        ``reserves.tonnage`` con los m³ del núcleo; el acopio, 6 240 t; su tabla y sus cifras
        (cada unidad y componente, los totales y las relaciones en total y por rodaja), finitas."""
        params = _parameters(self.case)
        out = volumes.tonnage_outputs(self.result.rows, self.column, params, name=NAME)
        volumes_all = [tonnage.UnitVolume("*", None, unit.code, float(value)) for unit, value
                       in zip(self.case.units, self.result.kernel.unit_volume_m3[kernel.ALL],
                              strict=True)]
        direct = tonnage.tonnage(volumes_all, self.column, params)
        self.assertEqual(out.result.total.total_t, direct.total.total_t)
        self.assertEqual(out.result.row("acopio").mass_t, direct.row("acopio").mass_t)
        self.assertLessEqual(abs(direct.row("acopio").mass_t - 6_240.0), CLOSURE * 6_240.0)
        mass = table.filter_rows(out.rows, domain="*", bench=None, unit="acopio",
                                 component=None, quantity="mass_t")
        self.assertEqual([row.value for row in mass], [direct.row("acopio").mass_t])
        found = _figures(out)
        self.assertEqual(found[("res.total_t", _scope())].value, direct.total.total_t)
        self.assertEqual(found[("res.unit_t", _scope(unit="acopio"))].value,
                         direct.row("acopio").mass_t)
        self.assertEqual(found[("res.unit_t", _scope(unit="capa_util", component="caliza"))]
                         .value, direct.row("capa_util", "caliza").mass_t)
        self.assertIn(("res.waste_ratio_t", _scope()), found)
        self.assertIn(("res.intrinsic_ratio_t", _scope(unit="capa_util")), found)
        self.assertIn(("res.total_t", _scope(bench=600.0)), found)
        self.assertEqual(out.warnings, ())
        for figure in out.figures:
            self.assertTrue(math.isfinite(figure.value), figure)

    def test_what_is_missing_is_a_note_never_a_nan(self) -> None:
        """RF-011-17, RF-011-22: sin la densidad de la montera, su masa y el total de toneladas
        no son cifra: en la tabla, sin valor y con su nota, el aviso con la unidad y el
        parámetro, y ninguna cifra NaN ni infinita."""
        params = _parameters(self.case)
        del params[res_params.density_key("montera")]
        out = volumes.tonnage_outputs(self.result.rows, self.column, params, name=NAME)
        found = _figures(out)
        self.assertNotIn(("res.total_t", _scope()), found)
        self.assertNotIn(("res.unit_t", _scope(unit="montera")), found)
        total = table.filter_rows(out.rows, domain="*", bench=None, quantity="total_t")
        self.assertEqual([(row.value, row.note) for row in total],
                         [(None, "res.note_no_density")])
        self.assertEqual([item.code for item in out.warnings], ["res.density_missing"])
        self.assertIn("res.unit.montera.density", out.warnings[0].text())
        for figure in out.figures:
            self.assertTrue(math.isfinite(figure.value), figure)
        for row in out.rows:
            self.assertTrue(row.value is None or math.isfinite(row.value), row)

    def test_a_negative_thickness_is_rejected(self) -> None:
        """RF-011-14: una rejilla de espesores con un espesor negativo se rechaza con la unidad y
        el menor valor (``res.thickness_negative``)."""
        thickness = self.case.units[0].thickness.values.copy()
        thickness[30, 20] = -0.25
        sources = {**self.sources, volumes.thickness_role("acopio"): _source(
            _write(self.folder / "espesor_negativo.tif", thickness, self.case.grid), "Neg")}
        with self.assertRaises(res_messages.ResError) as caught:
            _run(self.request_for(self.column), sources)
        self.assertEqual(caught.exception.code, "res.thickness_negative")
        self.assertIn("-0,25", caught.exception.text)


class ScaleTest(unittest.TestCase):
    """El factor combinado (A14; D-4 de la spec, D-34): se informa, no se aplica."""

    def test_combined_factor_at_1000_m(self) -> None:
        """D-34: a 1 000 m, el factor de elevación R/(R + h) con R = 6 371 000 m da un efecto en
        áreas y volúmenes de ≈ 0,03 % (1/F² − 1); con el de la proyección (k = 0,9996), los dos
        juntos (≈ 0,11 %)."""
        alone = scale.combined_factor(1.0, 1_000.0)
        self.assertAlmostEqual(alone.elevation_factor, 6_371_000.0 / 6_372_000.0, places=15)
        self.assertAlmostEqual(alone.effect_pct, 0.0314, places=4)
        both = scale.combined_factor(0.9996, 1_000.0)
        self.assertAlmostEqual(both.combined, 0.9996 * alone.elevation_factor, places=15)
        self.assertAlmostEqual(both.effect_pct,
                               ((1.0 + alone.effect_pct / 100.0) / 0.9996 ** 2 - 1.0) * 100.0,
                               places=12)
        self.assertAlmostEqual(both.effect_pct, 0.1115, places=4)
        for wrong in ((0.0, 0.0), (math.nan, 0.0), (1.0, math.inf), (1.0, -7_000_000.0)):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                scale.combined_factor(*wrong)

    def test_center_and_figures_of_a_cubication(self) -> None:
        """D-34: el punto del factor es el centro del ámbito (o de la rejilla); la cubicación da
        las cifras del factor combinado con la cota media de las dos superficies en las celdas
        con dato."""
        pair = fx.pyramid(2.0)
        grid = pair.grid
        self.assertEqual(scale.center(grid), fx.PYRAMID_CENTER)
        ring = np.array([[735_110.0, 4_434_120.0], [735_150.0, 4_434_120.0],
                         [735_150.0, 4_434_200.0]])
        self.assertEqual(scale.center(grid, (polygons.Polygon(1, "a", (ring,)),)),
                         (735_130.0, 4_434_160.0))
        with project_tmp("gb-011-t13-") as folder:
            sources = {volumes.START: _source(_write(folder / "a.tif", pair.start.values, grid),
                                              "A"),
                       volumes.FINAL: _source(_write(folder / "b.tif", pair.final.values, grid),
                                              "B")}
            request = volumes.VolumeRequest(NAME, SurfaceRef(dataset="a"),
                                            SurfaceRef(dataset="b"), point_scale=0.9996)
            result = _run(request, sources)[1]
        mean = float(np.mean((pair.start.values + pair.final.values) / 2.0))
        self.assertAlmostEqual(result.mean_elevation_m, mean, delta=1e-9 * mean)
        expected = scale.combined_factor(0.9996, result.mean_elevation_m)
        self.assertEqual(result.factor, expected)
        found = _figures(result)
        self.assertEqual(found[("res.grid_scale_factor", _scope())].value, expected.combined)
        self.assertEqual(found[("res.ground_effect_pct", _scope())].value, expected.effect_pct)
        self.assertEqual(found[("res.grid_scale_factor", _scope())].unit, "-")
        self.assertEqual(found[("res.ground_effect_pct", _scope())].unit, "%")


class TableTest(unittest.TestCase):
    """La tabla ``report`` en formato largo (D-27): columnas tipadas, lectura y filtro."""

    def test_round_trip_and_filters(self) -> None:
        """D-27, RF-011-22: la tabla se crea con sus columnas tipadas y sus títulos; sus filas
        se escriben y se leen iguales; se filtran por dominio, rodaja, unidad y dato; un valor
        NaN o infinito no es una fila."""
        rows = (
            table.row("cut_m3", 10.5),
            table.row("cut_m3", 4.25, domain="Fase 1"),
            table.row("cut_m3", 6.25, domain=""),
            table.row("cut_m3", 3.0, bench=(600.0, 610.0)),
            table.row("volume_m3", 2.0, unit="montera", bench=(600.0, 610.0)),
            table.row("mass_t", None, unit="montera", notes=("res.note_no_density",)),
            table.row("cut_m3", 0.5, bench=(None, 600.0)),
        )
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(table.create_table("res_vol_mensual_v01"))
            types = {name: kind for _cid, name, kind, *_rest in
                     conn.execute("PRAGMA table_info(res_vol_mensual_v01)")}
            self.assertEqual(types["value"], "DOUBLE")
            self.assertEqual(types["quantity"], "TEXT")
            conn.executemany(table.insert_sql("res_vol_mensual_v01"),
                             [row.values() for row in rows])
            self.assertEqual(table.read_rows(conn, "res_vol_mensual_v01"), rows)
        finally:
            conn.close()
        self.assertEqual(set(table.TITLES), set(table.COLUMN_NAMES))
        self.assertEqual(rows[5].unit_code, "t")
        self.assertEqual(rows[5].notes, ("res.note_no_density",))
        self.assertEqual(table.filter_rows(rows, domain="*", bench=None, unit=None), rows[:1])
        self.assertEqual(table.filter_rows(rows, bench=(600.0, 610.0)), rows[3:5])
        self.assertEqual(table.filter_rows(rows, unit="montera", quantity="mass_t"), rows[5:6])
        self.assertEqual(table.choices(rows).domains, ("*", "Fase 1", ""))
        self.assertEqual(table.choices(rows).benches, ((None, 600.0), (600.0, 610.0)))
        self.assertEqual(table.choices(rows).units, ("montera",))
        for wrong in (math.nan, math.inf):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                table.row("cut_m3", wrong)
        with self.assertRaises(ValueError):
            table.create_table("res_vol; DROP")


if __name__ == "__main__":
    unittest.main()
