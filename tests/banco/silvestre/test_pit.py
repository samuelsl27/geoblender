# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de la corta por bancos (spec 018, T38 y T38b; CE-018-12; DIFF-018l; HU-018-1; RF-018-27; plan 018 §7.1, «Banco de Silvestre»; D-11).

Solo la ejecuta el arnés de los bancos con el banco real (``tools/check.py --banco``, con ``GEOBLENDER_SILVESTRE_DIR``, de solo lectura); sin él, se omite con la orden que la activa
y **CE-018-12 queda «sin ejecutar con los datos originales»** (como CE-017-10: la omisión no cuenta como verde, ``definicion-de-hecho.md`` §3).
``tests/unit/design/test_pit_bank.py`` comprueba, con datos sintéticos y en el «verde», la comparación (:func:`outside`) y que esta prueba se omite.
La mitad sintética de CE-018-12 (la corta circular contra el escalonado de la 013, ≤ 1 % con celdas de ≤ 2 m) no necesita el banco y está en
``tests/referencia/des/test_ref_pit_report.py`` (T20b).

**Lo que se compara (DIFF-018l: dos fondos).** La cantera de la referencia tiene **dos fondos** (el principal y el de levante, a cotas distintas de la retícula del perfil) y **no** una cota de
fondo única: una corta descendente desde el perímetro con una sola cota de parada baja por todo el contorno (+658 % de volumen en la primera ejecución) y, además, el perímetro cae en el hueco
antiguo, por debajo de cualquier cota de fondo posible. Por eso la comparación es una corta **ascendente desde los fondos de la referencia, cada uno a su cota** (RF-018-02), con el **perfil de
explotación de la V10**, frente a **su superficie de explotación**: es el modo que ya admite la 018 (sin tocar ningún RF) y el sentido en que se construyó la referencia (el muro que sube del fondo).
Todo sale de la ficha de la cantera del banco (la de la 014, ``test_quarry``: el perfil y el ancla de la explotación, el recinto excavable y la superficie de explotación de la referencia, en la
rejilla y el CRS de su superficie final) y de la superficie de partida del banco; no se escribe ningún nombre de fichero ni la ruta del banco. Los **fondos** (:func:`floors_of`) son las mesetas
planas de la superficie de explotación de la referencia, a una cota de la retícula del perfil, bajo la partida y **sin terreno más bajo alrededor** (ninguna cara baja desde su borde: las bermas
tienen su cara por un lado); la corta se calcula con ``design.pit_bench.ascend`` y ``design.pit_surface.rasterize`` con las máscaras abiertas, sin rampa ni sector ni roseta: el banco de la 014
no trae croquis de rampas ni de sectores (como el de la 017 no trae los ejes), así que **no se inventan**. Los valores de desfase son HIPÓTESIS de este banco (``ARC_M`` y ``SIMPLIFY_M``, más
holgados que los de D-14 porque el borde de un fondo sale de una máscara de celdas).

**La tolerancia** (HIPÓTESIS, D-11): la de contraste de la 013, ``VOLUME_TOL`` = 1 % relativo en el volumen de excavación dentro del recinto (``Σ (partida − superficie) · área de
celda`` donde la superficie queda por debajo de la partida). Nunca se ajusta para que pase. Una diferencia que sobrepase la tolerancia con los datos reales la explica la persona
que ejecuta (la referencia lleva rampas y sectores que aquí no están), y se decide entonces con Samuel si se afina la tolerancia o la ficha; esta prueba **no lo decide**.

**La forma del banco**: la de la ficha de la 014 (véase ``test_quarry``). Lo que no está se dice con su motivo (``BankShapeError``); lo que está y no tiene esa forma falla.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import dataclass
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
ARC_M = 0.2
SIMPLIFY_M = 1.0
"""HIPÓTESIS de este banco (D-14): el borde de un fondo sale de una máscara de celdas; con 0,05 m las aristas se cruzan en el triangulador."""
MASK_LEVEL = 0.5
FLAT_TOL_M = 0.05
"""Una celda es plana a la cota de un banco si la referencia dista de ella a lo sumo esto (m; HIPÓTESIS)."""
MIN_DEPTH_M = 0.5
"""Un fondo está al menos esto (m) bajo la partida: lo que no excava no es un fondo."""
MIN_FLOOR_M2 = 1000.0
"""Área mínima de un fondo (m²; HIPÓTESIS)."""
MAX_LOWER_SHARE = 0.2
"""Parte máxima de las celdas de alrededor (a ``RING_CELLS``) que pueden estar más bajas que la meseta para que sea un fondo y no una berma (HIPÓTESIS): un fondo tiene sus caras hacia
arriba por todo su borde, salvo las rampas; una berma tiene la cara por un lado (cerca de la mitad)."""
RING_CELLS = 2


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
    """El contorno de una máscara (el borde de un fondo): la mayor curva cerrada de la máscara ``area`` (celdas con dato distinto de 0) como anillo ``(k, 2)`` absoluto, float64.
    :class:`BankShapeError` si la máscara no tiene ninguna curva cerrada (toca el borde de la rejilla o está vacía)."""
    values = np.where(area, 1.0, 0.0)
    lines = contours.contours_from_raster(raster_mod.Raster(grid, values, crs, vertical), interval_m=1.0, base_m=MASK_LEVEL)
    closed = [line for line in lines if line.closed]
    if not closed:
        raise BankShapeError("la máscara no tiene ninguna curva cerrada: no hay contorno (¿toca el borde de la rejilla?)")
    best = max(closed, key=lambda line: line.length_m)
    return np.ascontiguousarray(best.xyz[:, :2], dtype=np.float64)


def _components(mask: np.ndarray) -> list[np.ndarray]:
    """Las componentes conexas (4 vecinos) de ``mask`` como arrays de índices planos (sin ``scipy``: es solo para el banco)."""
    rows, cols = mask.shape
    flat = mask.ravel()
    seen = np.zeros(flat.size, bool)
    found: list[np.ndarray] = []
    for first in np.flatnonzero(flat):
        if seen[first]:
            continue
        seen[first] = True
        queue, members = [int(first)], []
        while queue:
            index = queue.pop()
            members.append(index)
            row, col = divmod(index, cols)
            for r, c in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if 0 <= r < rows and 0 <= c < cols:
                    other = r * cols + c
                    if flat[other] and not seen[other]:
                        seen[other] = True
                        queue.append(other)
        found.append(np.asarray(members, dtype=np.int64))
    return found


def _dilated(mask: np.ndarray, cells: int) -> np.ndarray:
    grown = mask.copy()
    for _ in range(cells):
        step = grown.copy()
        step[1:] |= grown[:-1]
        step[:-1] |= grown[1:]
        step[:, 1:] |= grown[:, :-1]
        step[:, :-1] |= grown[:, 1:]
        grown = step
    return grown


def floors_of(reference: np.ndarray, start: np.ndarray, area: np.ndarray, anchor_m: float, height_m: float, cell_area_m2: float) -> list[tuple[float, np.ndarray]]:
    """Los fondos de la superficie ``reference`` dentro de ``area``: ``(cota, máscara)`` de cada meseta plana (a ``FLAT_TOL_M``) a una cota ``anchor_m + k·height_m``, al menos ``MIN_DEPTH_M`` bajo
    ``start``, de al menos ``MIN_FLOOR_M2`` y con a lo sumo ``MAX_LOWER_SHARE`` de las celdas de su alrededor (``RING_CELLS``) más bajas que ella (CALCULADO; el criterio es una HIPÓTESIS del banco)."""
    valid = area & np.isfinite(reference) & np.isfinite(start)
    if not valid.any():
        return []
    low, high = float(reference[valid].min()), float(reference[valid].max())
    first, last = int(np.ceil((low - anchor_m) / height_m - 1e-9)), int(np.floor((high - anchor_m) / height_m + 1e-9))
    found: list[tuple[float, np.ndarray]] = []
    for k in range(first, last + 1):
        level = anchor_m + k * height_m
        plateau = valid & (np.abs(reference - level) <= FLAT_TOL_M) & (start - reference >= MIN_DEPTH_M)
        for members in _components(plateau):
            if len(members) * cell_area_m2 < MIN_FLOOR_M2:
                continue
            mask = np.zeros(reference.shape, bool)
            mask.ravel()[members] = True
            around = _dilated(mask, RING_CELLS) & ~mask & valid
            if not around.any() or float((reference[around] < level - MIN_DEPTH_M).sum()) / float(around.sum()) > MAX_LOWER_SHARE:
                continue
            found.append((level, mask))
    return found


def pit_surface_from_floors(floors: Sequence[tuple[float, np.ndarray]], start: np.ndarray, grid: object, crs: object, vertical: object, profile: object) -> np.ndarray:
    """La superficie de la corta ascendente desde ``floors`` (cada uno a su cota, RF-018-02) con ``profile``, sobre la partida ``start`` (m, float64). Sin rampas, sectores ni intocables."""
    sources = tuple(pit_model.PitSource(f"fondo {level:g} m ({index + 1})", perimeter_of(mask, grid, crs, vertical), level) for index, (level, mask) in enumerate(floors))
    job = pit_model.PitJob(
        request=pit_model.PitRequest(name="Corta del banco", fields=pit_model.LayerFields(layer="gis_fea_fondos", name_field="nombre"), mode="up", start="terreno", level_field="cota_m"),
        code="PIT-001", grid=grid, start=start, cut_allowed=np.ones(grid.shape, bool), fill_allowed=np.zeros(grid.shape, bool), untouchable=np.zeros(grid.shape, bool),
        sources=sources, params=pit_model.PitParams(arc_tol_m=ARC_M, simplify_m=SIMPLIFY_M), profile=profile)
    return np.asarray(pit_surface.rasterize(job, pit_bench.ascend(job), crs=crs, vertical=vertical).surface, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Comparison:
    """El resultado de :func:`compare`: la excavación de la corta y la de la referencia (m³), las celdas del recinto y, de cada fondo, ``(cota, celdas)``."""

    found_m3: float
    expected_m3: float
    cells: int
    floors: tuple[tuple[float, int], ...]


def compare(folder: Path) -> Comparison:
    """CE-018-12 sobre el banco ``folder`` (véase el módulo). :class:`BankShapeError` si falta algo o no hay ningún fondo."""
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
    cell = float(grid.cell_area)
    profile = sheet.exploitation.profile
    floors = floors_of(reference, start, area, float(profile.anchor_m), float(profile.height_m), cell)
    if not floors:
        raise BankShapeError("la superficie de explotación de la referencia no tiene ningún fondo (meseta plana a una cota de la retícula, sin terreno más bajo alrededor)")
    surface = pit_surface_from_floors(floors, start, grid, crs, vertical, profile)
    return Comparison(excavation_m3(start, surface, area, cell), excavation_m3(start, reference, area, cell), int(area.sum()),
                      tuple((level, int(mask.sum())) for level, mask in floors))


class ReferenceBankPitTest(unittest.TestCase):
    """CE-018-12 con el banco del proyecto de referencia (RF-018-27)."""

    folder: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = bank.bank_folder()

    def test_the_ascending_pit_from_the_reference_floors_with_the_reference_profile_matches_its_exploitation_surface(self) -> None:
        """CE-018-12: la corta ascendente desde los fondos de la referencia (cada uno a su cota) con el perfil de explotación de la V10, frente a su superficie de explotación, dentro de la tolerancia de D-11."""
        result = compare(self.folder)
        found, expected = result.found_m3, result.expected_m3
        floors = ", ".join(f"{level:g} m ({bank.number(float(cells), 0)} celdas)" for level, cells in result.floors)
        bank.report(f"{NAME}: excavación de la corta {bank.number(found)} m³ frente a {bank.number(expected)} m³ de la referencia en {bank.number(float(result.cells), 0)} celdas del recinto "
                    f"(diferencia {bank.percent((found - expected) / expected if expected else float('nan'))}; tolerancia {bank.percent(VOLUME_TOL)}); fondos: {floors}")
        self.assertFalse(outside(found, expected), f"{NAME}: la excavación de la corta difiere de la de la referencia más de {bank.percent(VOLUME_TOL)}")


if __name__ == "__main__":
    unittest.main()
