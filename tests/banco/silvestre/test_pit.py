# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de la corta por bancos (spec 018, T38; CE-018-12; HU-018-1; RF-018-27; plan 018 §7.1, «Banco de Silvestre»; D-11).

Solo la ejecuta el arnés de los bancos con el banco real (``tools/check.py --banco``, con ``GEOBLENDER_SILVESTRE_DIR``, de solo lectura); sin él, se omite con la orden que la activa
y **CE-018-12 queda «sin ejecutar con los datos originales»** (como CE-017-10: la omisión no cuenta como verde, ``definicion-de-hecho.md`` §3).
``tests/unit/design/test_pit_bank.py`` comprueba, con datos sintéticos y en el «verde», la comparación (:func:`outside`) y que esta prueba se omite.
La mitad sintética de CE-018-12 (la corta circular contra el escalonado de la 013, ≤ 1 % con celdas de ≤ 2 m) no necesita el banco y está en
``tests/referencia/des/test_ref_pit_report.py`` (T20b).

**Lo que se compara.** Una corta **descendente desde el perímetro de actuación** con el **perfil de explotación de la V10** frente a **su superficie de explotación**.
Todo sale de la ficha de la cantera del banco (la de la 014, ``test_quarry``: el perfil y el ancla de la explotación, el recinto excavable y la superficie de
explotación de la referencia, en la rejilla y el CRS de su superficie final) y de la superficie de partida del banco; no se escribe ningún nombre de fichero ni la ruta del banco.
El perímetro de actuación es el contorno del recinto de la ficha (la mayor curva cerrada de su máscara); la corta se calcula con ``design.pit_bench.descend`` y
``design.pit_surface.rasterize`` con las máscaras abiertas (sin intocables ni relleno), sin rampa ni sector ni roseta: el banco de la 014 no trae croquis de rampas ni de sectores
(como el de la 017 no trae los ejes), así que **no se inventan**. Los valores de desfase (``arc_tol_m`` y ``simplify_m``) son las HIPÓTESIS de D-14 de ``pit_data``.

**La tolerancia** (HIPÓTESIS, D-11): la de contraste de la 013, ``VOLUME_TOL`` = 1 % relativo en el volumen de excavación dentro del recinto (``Σ (partida − superficie) · área de
celda`` donde la superficie queda por debajo de la partida). Nunca se ajusta para que pase. Una diferencia que sobrepase la tolerancia con los datos reales la explica la persona
que ejecuta (la referencia lleva rampas y sectores que aquí no están), y se decide entonces con Samuel si se afina la tolerancia o la ficha; esta prueba **no lo decide**.

**La forma del banco**: la de la ficha de la 014 (véase ``test_quarry``). Lo que no está se dice con su motivo (``BankShapeError``); lo que está y no tiene esa forma falla.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.banco.silvestre import test_quarry as quarry_bank
from tests.support import bank_folder as bank
from tests.support.bank_folder import BankShapeError
from tests.support.package import import_geoblender

geotiff = import_geoblender("gis.geotiff")
raster_mod = import_geoblender("gis.raster")
contours = import_geoblender("gis.contours")
pit_model = import_geoblender("design.pit_model")
pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")

NAME = "CE-018-12"
VOLUME_TOL = 1e-2
"""D-11 (HIPÓTESIS): el contraste con la 013 a ≤ 1 % en volumen; es la cota con que se compara la excavación de la corta con la de la superficie de explotación de la referencia."""
ARC_M = 0.05
SIMPLIFY_M = 0.05
"""D-14 (HIPÓTESIS), los de ``tests/support/pit_data.HYPOTHESES``."""
MASK_LEVEL = 0.5


def outside(found: float, reference: float, tolerance: float = VOLUME_TOL) -> bool:
    """Verdadero si ``found`` difiere de ``reference`` más que ``tolerance`` relativo a ``reference`` (CE-018-12; D-11). Una referencia nula solo admite un hallado nulo."""
    if reference == 0.0:
        return found != 0.0
    return abs(found - reference) / abs(reference) > tolerance


def excavation_m3(start: np.ndarray, surface: np.ndarray, area: np.ndarray, cell_area_m2: float) -> float:
    """El volumen de excavación (m³) de ``surface`` bajo ``start`` dentro de ``area`` (máscara): ``Σ (partida − superficie) · área de celda`` donde baja (CALCULADO)."""
    drop = start - surface
    moved = area & np.isfinite(drop) & (drop > 0.0)
    return float(drop[moved].sum()) * cell_area_m2


def perimeter_of(area: np.ndarray, grid: object, crs: object, vertical: object) -> np.ndarray:
    """El perímetro de actuación: la mayor curva cerrada de la máscara ``area`` (celdas con dato distinto de 0) como anillo ``(k, 2)`` absoluto, float64.
    :class:`BankShapeError` si la máscara no tiene ninguna curva cerrada (toca el borde de la rejilla o está vacía)."""
    values = np.where(area, 1.0, 0.0)
    lines = contours.contours_from_raster(raster_mod.Raster(grid, values, crs, vertical), interval_m=1.0, base_m=MASK_LEVEL)
    closed = [line for line in lines if line.closed]
    if not closed:
        raise BankShapeError("el recinto de la ficha no tiene ninguna curva cerrada: no hay perímetro de actuación (¿toca el borde de la rejilla?)")
    best = max(closed, key=lambda line: line.length_m)
    return np.ascontiguousarray(best.xyz[:, :2], dtype=np.float64)


def compare(folder: Path) -> tuple[float, float, int]:
    """CE-018-12 sobre el banco ``folder``: ``(volumen de la corta, volumen de la referencia, celdas del recinto)`` en m³ (véase el módulo)."""
    version = bank.files(bank.find_version(folder))
    everything = bank.files(folder)
    problems: list[str] = []
    sheet = quarry_bank._read_sheet(version, everything, problems)
    starts = bank.distinct(bank.tiffs(version, bank.START_PATTERN) or bank.tiffs(everything, bank.START_PATTERN))
    if len(starts) != 1:
        problems.append(f"la superficie de partida (GeoTIFF con MDT, DEM, DTM o terreno en el nombre): se esperaba una y hay {quarry_bank._count(starts)}")
    paths = {} if sheet is None else quarry_bank._resolve(sheet, version, everything, problems)
    first = None if sheet is None else paths.get(quarry_bank._key(sheet.final.reference))
    if problems or sheet is None or first is None:
        raise BankShapeError(quarry_bank._shape_message(problems))
    if first.suffix.lower() not in bank.TIFF_SUFFIXES:
        raise BankShapeError(quarry_bank._shape_message(["la superficie final de la referencia es un .npy: tiene que ser un GeoTIFF, que da la rejilla y el CRS"]))
    final = geotiff.read_geotiff(first)
    crs, vertical = bank.declared(final, "la superficie final de la referencia")
    grid = final.grid
    arrays: dict[str, np.ndarray | None] = {}
    for what, stem in (("el recinto", sheet.area), ("la superficie de explotación de la referencia", sheet.exploitation.reference)):
        arrays[stem] = quarry_bank._read(paths[quarry_bank._key(stem)], grid, crs, what, problems)
    if problems:
        raise BankShapeError(quarry_bank._shape_message(problems))
    area_values, reference = arrays[sheet.area], arrays[sheet.exploitation.reference]
    assert area_values is not None and reference is not None  # sin problemas
    area = np.isfinite(area_values) & (area_values != 0.0)
    with tempfile.TemporaryDirectory(prefix="gb-banco-018-") as name:
        ready = bank.on_grid(starts[0], grid, crs, vertical, Path(name), "partida", "la superficie de partida")
        start = np.asarray(geotiff.read_geotiff(ready).values, dtype=np.float64)
    ring = perimeter_of(area, grid, crs, vertical)
    job = pit_model.PitJob(
        request=pit_model.PitRequest(name="Corta del banco", fields=pit_model.LayerFields(layer="gis_fea_limites", name_field="nombre"), mode="down", start="terreno"),
        code="PIT-001", grid=grid, start=start, cut_allowed=np.ones(grid.shape, bool), fill_allowed=np.zeros(grid.shape, bool), untouchable=np.zeros(grid.shape, bool),
        sources=(pit_model.PitSource("perímetro de actuación", ring, None),), params=pit_model.PitParams(arc_tol_m=ARC_M, simplify_m=SIMPLIFY_M),
        profile=sheet.exploitation.profile)
    surface = pit_surface.rasterize(job, pit_bench.descend(job), crs=crs, vertical=vertical)
    cell = float(grid.cell_area)
    found = excavation_m3(start, surface.surface, area, cell)
    expected = excavation_m3(start, reference, area, cell)
    return found, expected, int(area.sum())


class ReferenceBankPitTest(unittest.TestCase):
    """CE-018-12 con el banco del proyecto de referencia (RF-018-27)."""

    folder: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = bank.bank_folder()

    def test_the_descending_pit_with_the_reference_profile_matches_its_exploitation_surface(self) -> None:
        """CE-018-12: la corta descendente desde el perímetro de actuación con el perfil de explotación de la V10, frente a su superficie de explotación, dentro de la tolerancia de D-11."""
        found, expected, cells = compare(self.folder)
        bank.report(f"{NAME}: excavación de la corta {bank.number(found)} m³ frente a {bank.number(expected)} m³ de la referencia en {bank.number(float(cells), 0)} celdas del recinto "
                    f"(diferencia {bank.percent((found - expected) / expected if expected else float('nan'))}; tolerancia {bank.percent(VOLUME_TOL)})")
        self.assertFalse(outside(found, expected), f"{NAME}: la excavación de la corta difiere de la de la referencia más de {bank.percent(VOLUME_TOL)}")


if __name__ == "__main__":
    unittest.main()
