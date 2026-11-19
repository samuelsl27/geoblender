# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de los acopios (spec 016, T22; CE-016-08; HU-016-1, HU-016-2; RF-016-02, RF-016-08, RF-016-11, RF-016-16; plan 016 §5.7 P-6,
§7.1 y §11 S-3 y S-4; ``docs/decisiones-pendientes.md``).

Solo la ejecuta el arnés de los bancos con el banco real (``tools/check.py --banco``, con ``GEOBLENDER_SILVESTRE_DIR``, de solo lectura); sin él, se
omite. ``tests/unit/design/test_stockpile_bank.py`` comprueba, con datos sintéticos y en el «verde», sus ayudas y que se omite.

**Lo que el banco trae y lo que no** (dicho al ejecutarla, sin nombrar ningún fichero): el MDT de 0,5 m, el raster del stock de los nueve acopios de la V10 en
su rejilla de 1 m y la superficie *in situ* (con el plano de base de cada acopio) **sí**; **no trae** las nueve marcas originales, el volumen y la huella de
cada acopio en la rejilla de 0,5 m (193.008 m³ y 37.808 m² son los totales de la documentación) ni la superficie de restauración que partía la transición
(16.816 m³, con el factor de malla 0,93). Las marcas se **derivan** aquí del raster del stock (cada componente, crecida unas celdas sin tocar a la
vecina), así que una diferencia con la cifra de la V10 depende de la marca y no se puede atribuir al algoritmo: cuando algún acopio queda fuera de la
tolerancia de S-4 (≤ 1 % de volumen y de huella frente al raster del stock; ≤ 1 % de los totales de la documentación), la comparación **se omite** con
ese motivo (no cuenta como verde, ``definicion-de-hecho.md`` §3) y escribe, con la cifra de cada uno, qué diferencia hay. Las etiquetas de los acopios que se escriben son las del
raster (orden de lectura), no la numeración de la V10. Nunca se ajusta una tolerancia para que pase.
"""

from __future__ import annotations

import math
import re
import time
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tests.support import bank_folder as bank
from tests.support.package import import_geoblender

geotiff = import_geoblender("gis.geotiff")
grids = import_geoblender("design.grids")
stockpiles = import_geoblender("design.stockpiles")

NAME = "acopios"
REFERENCE_AREA_M2, REFERENCE_VOLUME_M3 = 37_808.0, 193_008.0
"""Los nueve acopios de la V10 en su rejilla de 0,5 m: huella y volumen totales (CE-016-08; la documentación del análisis de la V10, §3.8)."""
REFERENCE_PLANE_PCT = 3.76
"""La pendiente de la plataforma del acopio 7 de la V10 (CE-016-08; su cota media era 187,61 m y su área, 1,03 ha: la del plano **extendido** a la zona con el
relleno de la V09 que se le apoyaba, no la de la huella)."""
TOLERANCE = 0.01
"""S-4: volumen y huella de cada acopio ≤ 1 % frente a su cálculo (el plan 016 §11 S-4)."""
D3 = {"crown_inner_m": 1.0, "crown_outer_m": 3.0, "crown_slope_deg": 12.0, "crown_flat_min_m2": 10.0, "max_residual_m": 1.0, "fit_rounds": 4,
      "tilt_max_deg": 4.0, "support_quantile": 0.6}
"""Los umbrales de D-3 (datos de ENTRADA de la comparación; el plan los repite en §5.2.2)."""
THRESHOLD_M, MARGIN_M, TURNS = 0.30, 3.0, 6
"""El umbral de la huella de la 011 (D-17), el margen de cada marca derivada y las vueltas."""
GROW_CELLS = 8
"""Lo que se crece cada componente para hacer su marca (celdas de 0,5 m: 4 m), sin tocar a la vecina."""
OPENINGS = (("31 m de diámetro (la hipótesis P-6)", 31.0), ("31 celdas de 0,5 m (15,5 m de diámetro)", 15.5), ("un radio de 31 m (62 m de diámetro)", 62.0))
STOCK_PATTERN = re.compile(r"(?i)stock")
DEM_PATTERN = re.compile(r"(?i)^dem")
IN_SITU_PATTERN = re.compile(r"(?i)in_situ")


@dataclass(frozen=True, slots=True)
class Figures:
    """El área (m²) y el volumen (m³) de un acopio."""

    area_m2: float
    volume_m3: float


def relative(found: float, wanted: float) -> float:
    """La diferencia relativa de ``found`` frente a ``wanted`` (``found / wanted − 1``)."""
    return found / wanted - 1.0


def outside(found: Figures, wanted: Figures, tolerance: float = TOLERANCE) -> list[str]:
    """Lo que de ``found`` queda fuera de ``tolerance`` frente a ``wanted``: ``huella``, ``volumen``."""
    problems = []
    if abs(relative(found.area_m2, wanted.area_m2)) > tolerance:
        problems.append("huella")
    if abs(relative(found.volume_m3, wanted.volume_m3)) > tolerance:
        problems.append("volumen")
    return problems


def stock_labels(thickness: np.ndarray, *, skip_cells: int = 20) -> np.ndarray:
    """Los acopios del raster del stock (el espesor, NaN sin dato): una etiqueta por componente conexa de más de 0, **sin las de menos de ``skip_cells``
    celdas** (astillas: ``0``)."""
    found = grids.label_components(np.isfinite(thickness) & (thickness > 0.0)).grid.copy()
    for number in np.unique(found[found > 0]):
        if int((found == number).sum()) < skip_cells:
            found[found == number] = 0
    return found


def carry(labels: np.ndarray, source: object, target: object) -> np.ndarray:
    """Las ``labels`` de la rejilla ``source`` llevadas a la de ``target`` por la celda que contiene cada centro (la más próxima: sin remuestrear valores)."""
    cols = np.floor(((np.arange(target.ncols) + 0.5) * target.dx + target.west - source.west) / source.dx).astype(int)
    rows = np.floor((source.north - target.north + (np.arange(target.nrows) + 0.5) * target.dy) / source.dy).astype(int)
    inside = ((rows >= 0) & (rows < source.nrows))[:, None] & ((cols >= 0) & (cols < source.ncols))[None, :]
    taken = labels[np.clip(rows, 0, source.nrows - 1)[:, None], np.clip(cols, 0, source.ncols - 1)[None, :]]
    return np.where(inside, taken, 0)


def grow(labels: np.ndarray, cells: int) -> np.ndarray:
    """Cada etiqueta crecida ``cells`` celdas (8 vecinos por vuelta) donde no hay otra: las marcas quedan **sin celdas en común**."""
    rows, cols = np.nonzero(labels)
    if rows.size == 0:
        return labels.copy()
    top, bottom = max(int(rows.min()) - cells - 1, 0), min(int(rows.max()) + cells + 2, labels.shape[0])
    left, right = max(int(cols.min()) - cells - 1, 0), min(int(cols.max()) + cells + 2, labels.shape[1])
    found = labels[top:bottom, left:right].copy()
    for _ in range(cells):
        padded = np.pad(found, 1)
        near = np.maximum.reduce([padded[1 + dr:padded.shape[0] - 1 + dr, 1 + dc:padded.shape[1] - 1 + dc]
                                  for dr in (-1, 0, 1) for dc in (-1, 0, 1)])
        found = np.where(found == 0, near, found)
    whole = labels.copy()
    whole[top:bottom, left:right] = found
    return whole


def marks_of(labels: np.ndarray, *, margin_m: float = MARGIN_M) -> tuple[object, ...]:
    """Una ``StockpileMark`` por etiqueta (``Acopio <etiqueta>``) con sus celdas en la rejilla entera."""
    marks = []
    for number in np.unique(labels[labels > 0]):
        rows, cols = np.nonzero(labels == number)
        cells = np.sort(rows.astype(np.int64) * labels.shape[1] + cols)
        marks.append(stockpiles.StockpileMark(f"Acopio {int(number)}", cells, margin_m=margin_m))
    return tuple(marks)


def derive_and_detect(stock: object, dem: object) -> tuple[dict[int, Figures], dict[int, Figures], list[str]]:
    """Detecta los acopios sobre el MDT ``dem`` (con su ``grid``) con las marcas derivadas del raster del stock ``stock`` (el espesor; su rejilla puede ser otra):
    la huella y el volumen **del raster** por etiqueta, los **detectados** y las marcas que la detección rechazó."""
    source, grid = stock.grid, dem.grid
    thickness = np.asarray(stock.values, dtype=np.float64)
    labels = stock_labels(thickness)
    cell = source.dx * source.dy
    wanted = {int(n): Figures(float((labels == n).sum()) * cell, float(np.nansum(thickness[labels == n])) * cell)
              for n in np.unique(labels[labels > 0])}
    marks = marks_of(grow(carry(labels, source, grid), GROW_CELLS))
    params = stockpiles.FootprintParams(plane=stockpiles.PlaneParams(**D3), margin_m=MARGIN_M, turns=TURNS, threshold_m=THRESHOLD_M)
    outcome = stockpiles.detect_stockpiles(
        stockpiles.StockpileJob("Acopios", "STK-001", grid, np.asarray(dem.values, dtype=np.float64), marks, params))
    found = {int(item.key.split()[-1]): Figures(item.area_m2, item.volume_m3) for item in outcome.stockpiles}
    return wanted, found, [item.key for item in outcome.rejected]


class StockpilesBankTest(unittest.TestCase):
    """CE-016-08: los acopios de la V10 contra el banco, con lo que el banco trae (véase el módulo)."""

    folder: Path
    stock: object
    dem: object
    in_situ: object
    figures: dict[int, Figures]
    found: dict[int, Figures]
    problems: dict[int, list[str]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = bank.bank_folder()
        everything = bank.files(cls.folder)
        stock = bank.one(bank.tiffs(everything, STOCK_PATTERN), "el raster del stock de los acopios de la V10")
        dem = bank.one(bank.tiffs(everything, DEM_PATTERN), "el MDT de 0,5 m")
        in_situ = bank.one(bank.tiffs(everything, IN_SITU_PATTERN), "la superficie in situ (con el plano de base de los acopios)")
        cls.stock, cls.dem, cls.in_situ = (geotiff.read_geotiff(path) for path in (stock, dem, in_situ))
        for what, found in (("el raster del stock", cls.stock), ("el MDT", cls.dem), ("la superficie in situ", cls.in_situ)):
            bank.declared(found, what)
        cls.detect_all()

    @classmethod
    def detect_all(cls) -> None:
        """Detecta los acopios sobre el MDT de 0,5 m con las marcas derivadas del raster del stock y los compara con él (rejilla de 1 m, por acopio)."""
        cls.figures, cls.found, cls.rejected = derive_and_detect(cls.stock, cls.dem)
        cls.problems = {number: (outside(cls.found[number], wanted) if number in cls.found else ["rechazado"])
                        for number, wanted in cls.figures.items()}

    def test_the_nine_stockpiles_of_the_v10_are_the_ones_of_its_stock_raster(self) -> None:
        """CE-016-08, S-4, D-16, D-17, D-18: cada acopio detectado sobre el MDT de 0,5 m con su marca derivada, con la huella y el volumen del raster del
        stock (1 m) a ≤ 1 %, y los totales con los de la V10 (37.808 m² y 193.008 m³ en 0,5 m) a ≤ 1 %. Escribe la diferencia de cada acopio; si alguno
        queda fuera, **se omite** (las marcas son derivadas, no las originales: no se atribuye al algoritmo) y no cuenta como verde."""
        lines = []
        for number, wanted in sorted(self.figures.items()):
            have = self.found.get(number)
            if have is None:
                lines.append(f"acopio {number}: rechazado por la detección (huella de {bank.number(wanted.area_m2, 0)} m² en el raster)")
                continue
            lines.append(f"acopio {number}: huella {bank.number(have.area_m2, 0)} m² ({bank.percent(relative(have.area_m2, wanted.area_m2), 2)}), "
                         f"volumen {bank.number(have.volume_m3, 0)} m³ ({bank.percent(relative(have.volume_m3, wanted.volume_m3), 2)})")
        area = math.fsum(item.area_m2 for item in self.found.values())
        volume = math.fsum(item.volume_m3 for item in self.found.values())
        lines.append(f"totales: huella {bank.number(area, 0)} m² ({bank.percent(relative(area, REFERENCE_AREA_M2), 2)} de la V10), volumen "
                     f"{bank.number(volume, 0)} m³ ({bank.percent(relative(volume, REFERENCE_VOLUME_M3), 2)} de la V10)")
        for line in lines:
            bank.report(f"{NAME}: {line}")
        bad = sorted(number for number, found in self.problems.items() if found)
        totals = outside(Figures(area, volume), Figures(REFERENCE_AREA_M2, REFERENCE_VOLUME_M3))
        if bad or totals:
            raise unittest.SkipTest(
                f"OMITIDO: silvestre: {len(bad)} de {len(self.figures)} acopios (y los totales: {', '.join(totals) or 'bien'}) fuera del {TOLERANCE:.0%} de S-4 "
                "con las marcas derivadas del raster del stock: el banco no trae las marcas originales ni las cifras por acopio en 0,5 m, así que la diferencia "
                "depende de la marca y no es atribuible al algoritmo (CE-016-08 sin contrastar)")
        self.assertEqual(self.rejected, [])

    def test_the_platform_of_the_stockpile_of_the_platform_is_the_plane_of_its_base(self) -> None:
        """CE-016-08, RF-016-16, A9: el plano de la base del acopio de la plataforma (el de menor cota media) por mínimos cuadrados sobre su huella en la
        superficie in situ da **la pendiente del 3,76 %** de la V10 (a ± 0,02 puntos) con un residuo de la base de ≤ 0,02 m; su cota media y su área (la
        de la **huella**) se escriben: la V10 daba 187,61 m y 1,03 ha, que eran las del plano extendido a la zona del relleno de la V09 apoyado, no las
        de la huella (la diferencia que explica el plan, S-4)."""
        labels = stock_labels(np.asarray(self.stock.values, dtype=np.float64))
        source = self.stock.grid
        base = np.asarray(self.in_situ.values, dtype=np.float64)
        means = {int(n): float(np.nanmean(base[labels == n])) for n in np.unique(labels[labels > 0])}
        number = min(means, key=means.__getitem__)
        mask = labels == number
        rows, cols = np.nonzero(mask)
        x = source.west + (cols + 0.5) * source.dx
        y = source.north - (rows + 0.5) * source.dy
        design = np.column_stack([x - x.mean(), y - y.mean(), np.ones(len(x))])
        levels = base[mask]
        coefficients = np.linalg.lstsq(design, levels, rcond=None)[0]
        gradient = 100.0 * math.hypot(coefficients[0], coefficients[1])
        residual = float(np.max(np.abs(design @ coefficients - levels)))
        area = float(mask.sum()) * source.dx * source.dy
        bank.report(f"{NAME}: plataforma del acopio de menor cota: pendiente {bank.number(gradient, 3)} % (V10: {REFERENCE_PLANE_PCT} %), cota en el centro de la "
                    f"huella {bank.number(coefficients[2], 2)} m (V10: 187,61 m en la zona extendida), huella {bank.number(area / 1e4, 2)} ha (V10: 1,03 ha en la "
                    f"zona extendida), residuo de la base {bank.number(residual, 3)} m")
        bank.report(f"{NAME}: la transición de los acopios retirados (16.816 m³, factor de malla 0,93) NO se contrasta: se medía sobre la superficie de "
                    "restauración que partía la retirada, que el banco no trae (CE-016-08 sin contrastar en ese punto)")
        self.assertAlmostEqual(gradient, REFERENCE_PLANE_PCT, delta=0.02)
        self.assertLessEqual(residual, 0.02)

    def test_the_opening_of_31_m_is_reported_with_its_alternatives(self) -> None:
        """CE-016-08, P-6, S-3, RF-016-08: la apertura de los candidatos con las tres lecturas del «31 m» sobre el MDT (sin el índice de vegetación ni el
        perímetro de la V10): **escribe** cuántos candidatos da cada una y cuántos de los acopios del stock aparecen entre ellos, y comprueba lo único que es un
        hecho —con un disco mayor sobresalen más zonas: los candidatos no disminuyen con el diámetro—. **No confirma P-6**: la V10 daba 60 candidatos con el
        filtro de vegetación (R-30) y la concesión, que el banco no trae; la hipótesis de S-3 sigue siendo una hipótesis."""
        source, grid = self.stock.grid, self.dem.grid
        known = carry(stock_labels(np.asarray(self.stock.values, dtype=np.float64)), source, grid)
        values = np.asarray(self.dem.values, dtype=np.float64)
        footprint = stockpiles.FootprintParams(plane=stockpiles.PlaneParams(**D3), margin_m=10.0, turns=TURNS, threshold_m=THRESHOLD_M)
        perimeter = np.isfinite(values)
        counts = []
        for label, diameter in OPENINGS:
            began = time.perf_counter()
            params = stockpiles.CandidateParams(open_diameter_m=diameter, min_height_m=2.0, min_area_m2=150.0, max_area_m2=20_000.0, footprint=footprint)
            found = stockpiles.find_candidates(values, grid, perimeter, None, params)
            hit = set()
            for item in found.items:
                labelled = known.reshape(-1)[item.cells]
                hit |= {int(n) for n in np.unique(labelled[labelled > 0])}
            counts.append((diameter, len(found.items)))
            bank.report(f"{NAME}: apertura de {label}: {len(found.items)} candidatos de {found.zones} zonas; entre ellos {len(hit)} de los acopios del stock "
                        f"({time.perf_counter() - began:.0f} s)")
        bank.report(f"{NAME}: la V10 daba 60 candidatos con el índice de vegetación y la concesión: sin ellos no hay cifra con que contrastar; el «31 m» de P-6 NO "
                    "queda confirmado (CE-016-08 sin contrastar en ese punto)")
        ordered = sorted(counts)
        self.assertEqual([number for _diameter, number in ordered], sorted(number for _diameter, number in ordered))


if __name__ == "__main__":
    unittest.main()
