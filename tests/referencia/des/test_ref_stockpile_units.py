# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-016-07: regresión de los errores 52 y 67 con la base y el espesor de los acopios (spec 016, T16; HU-016-1; RF-016-09,
RF-011-14, RF-011-16; D-17 y D-19 de la 016; plan 016 §5.6 y H-1; ADR-0031 §3; plan 011 A7 y D-23).

La cubicación de la 011 toma cada material de una detección de acopios como **una unidad antrópica** por su base y su rejilla
de espesores (``reserves.materials.Unit.base`` y ``.thickness``: dos rejillas dispersas, con NaN fuera de las huellas), con el
umbral único de presencia de la 011 (``res.anthropic_presence_m``, D-17) y la densidad suelta. **La 011 no cambia**: esta prueba
comprueba que su núcleo (``reserves.kernel``), su lectura de ficheros (``reserves.surfaces``) y sus pasos
(``reserves.volumes.volume_steps``) hacen con esas rejillas lo que pide CE-016-07, sobre **GeoTIFF reales** del perfil
``project`` escritos como los deja la detección (la cantera de los acopios de 2 m: cinco marcas, dos materiales, dos de ellos
con las huellas pegadas; el Acopio 5, con una base propia):

- el volumen de cada unidad es **el de la detección** (la suma de los volúmenes de sus acopios) a ≤ 10⁻⁹ relativo, también
  leído por bandas de 32 filas (que parten las huellas) y calculado **a mano** celda a celda con ``math.fsum``;
- las celdas de la unidad son las de la huella (las de su espesor sobre el umbral) y la unidad está ausente en el resto de
  la rejilla (que, por ser dispersa, cuenta como «sin dato» de su base: la tabla de la 011 lo dice, no es un aviso);
- **0 m³ de las demás unidades por encima de la base en las huellas**: con el terreno sin acopios como superficie de partida
  los acopios no tienen volumen y la unidad del terreno es **la misma** que con los acopios encima;
- con dos materiales, dos unidades (con uno, una) y un acopio suelto pesa **V·ρ/K** toneladas (no V·ρ: error 67), cada
  unidad con su densidad y su K;
- la detección **no da toneladas propias**: ni una cifra ni una columna de sus tablas (errores 52, 63 y 67: una sola
  cubicación).

Los ρ y K de la prueba son **sintéticos** (no son de ningún material real: D-8); el umbral de presencia es el de la detección
(``params.threshold_m``).
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design.test_stockpile_footprint import params_of

gis = import_geoblender("gis")
writer = import_geoblender("gis.geotiff.writer")
kernel = import_geoblender("reserves.kernel")
materials = import_geoblender("reserves.materials")
res_params = import_geoblender("reserves.params")
surfaces = import_geoblender("reserves.surfaces")
volumes = import_geoblender("reserves.volumes")
design_provenance = import_geoblender("design.provenance")
design_store = import_geoblender("design.store")
stockpiles = import_geoblender("design.stockpiles")

GRID = ops.GRID
CELL_M2 = GRID.cell_area
TOLERANCE = 1e-9
"""El error relativo admitido frente a la detección y a mano (D-11 de la 016; CE-016-07)."""
BAND = 32
"""Las filas de una banda: las huellas cruzan sus límites."""
NAME = "Acopios cubicados"
MINERAL, WASTE = "mineral", "estéril"
SYNTHETIC = {MINERAL: (2.60, 1.50), WASTE: (2.10, 1.30), "terreno": (2.40, 1.20)}
"""La densidad (t/m³) y el K de cada unidad: valores sintéticos de prueba, distintos en cada una para que se note cualquier cruce."""
CODES = {MINERAL: "acopio_mineral", WASTE: "acopio_esteril"}
ROLES = {MINERAL: materials.Role.USEFUL, WASTE: materials.Role.WASTE}
GROUND = "terreno"


def _base_name(material: str) -> str:
    return f"base_{CODES[material]}"


def _thickness_name(material: str) -> str:
    return f"espesor_{CODES[material]}"


class Cubication:
    """Una cubicación de la 011 sobre ficheros GeoTIFF reales: lo escrito de la detección ``outcome`` (la base y el espesor
    dispersos de cada material, como los deja ``stockpile_store``), la superficie de partida ``start`` y una final constante por
    debajo de todo, con una unidad por material y la del terreno al final. Da el resultado de ``volume_steps`` y las toneladas."""

    def __init__(self, folder: Path, outcome: Any, start: np.ndarray, *, tag: str, band_rows: int = BAND,
                 states: dict[str, str] | None = None) -> None:
        self.outcome = outcome
        self.folder = folder
        self.floor = math.floor(min(float(np.nanmin(start)), *(float(np.nanmin(item.base)) for item in outcome.stockpiles))) - 5.0
        self.states = states or {}
        files = {"start": self._write(f"partida_{tag}", start)}
        self.materials = tuple(outcome.materials)
        for material in self.materials:
            files[_base_name(material)] = self._write(f"{_base_name(material)}_{tag}", outcome.base_grid(material))
            files[_thickness_name(material)] = self._write(f"{_thickness_name(material)}_{tag}", outcome.thickness_grid(material))
        self.column = self._column()
        self.request = volumes.VolumeRequest(NAME, surfaces.SurfaceRef(dataset="partida"), surfaces.SurfaceRef(elevation=self.floor),
                                             column=self.column, presence_m=outcome_threshold())
        self.sources = {volumes.START: self._source(files["start"], "Partida"),
                        volumes.FINAL: surfaces.constant_source(self.floor, name="Cota de fondo", crs=sdata.CRS, vertical=sdata.VERTICAL)}
        for unit in self.column.units[:-1]:
            material = next(found for found, code in CODES.items() if code == unit.code)
            self.sources[volumes.base_role(unit.code)] = self._source(files[_base_name(material)], unit.base.shown)
            self.sources[volumes.thickness_role(unit.code)] = self._source(files[_thickness_name(material)], unit.thickness.shown)
        self.result = list(volumes.volume_steps(self.request, self.sources, band_rows=band_rows))[-1].result

    def _write(self, name: str, values: np.ndarray) -> Path:
        path = self.folder / f"{name}.tif"
        writer.write_geotiff(gis.Raster(GRID, values, sdata.CRS, sdata.VERTICAL), path, profile="project")
        return path

    @staticmethod
    def _source(path: Path, name: str) -> Any:
        return surfaces.grid_source(path, name=name, crs=sdata.CRS, vertical=sdata.VERTICAL)

    def _column(self) -> Any:
        """Una unidad antrópica suelta por material (su base y su espesor: los datos de la detección) y el terreno in situ."""
        units = [materials.Unit(CODES[material], f"Acopios de {material}", materials.Kind.ANTHROPIC, ROLES[material],
                                self.states.get(material, materials.State.LOOSE),
                                surfaces.SurfaceRef(dataset=_base_name(material)),
                                surfaces.SurfaceRef(dataset=_thickness_name(material)))
                 for material in self.materials]
        units.append(materials.Unit(GROUND, "Terreno", materials.Kind.NATURAL, materials.Role.WASTE, materials.State.IN_SITU))
        return materials.MaterialColumn(tuple(units))

    def volume(self, code: str) -> float:
        """El volumen (m³) de la unidad ``code`` en el total de la cubicación."""
        index = self.column.codes.index(code)
        return float(self.result.kernel.unit_volume_m3[kernel.ALL][index])

    def area(self, name: str, code: str) -> float:
        """El área (m²) ``unit_<name>_m2`` de la unidad ``code`` en el total."""
        index = self.column.codes.index(code)
        return float(getattr(self.result.kernel, f"unit_{name}_m2")[kernel.ALL][index])

    def weighed(self) -> Any:
        """Las toneladas de la cubicación con los ρ y K de :data:`SYNTHETIC` de cada unidad."""
        params: dict[str, float] = {}
        for unit in self.column.units:
            density, swell = SYNTHETIC[next((m for m, code in CODES.items() if code == unit.code), GROUND)]
            params[res_params.density_key(unit.code)] = density
            params[res_params.swell_key(unit.code)] = swell
        return volumes.tonnage_outputs(self.result.rows, self.column, params, name=NAME)


def outcome_threshold() -> float:
    """El umbral de huella de la detección de la cantera (el de la 011, D-17)."""
    return float(params_of().threshold_m)


def hand_volume(outcome: Any, start: np.ndarray, material: str) -> float:
    """El volumen **a mano** de los acopios de ``material``: ``Σ (z − base)·A`` de las celdas de sus huellas donde pasa del umbral,
    con ``z`` del levantamiento y ``base`` de la detección, en un bucle con ``math.fsum``."""
    found = []
    for item in outcome.stockpiles:
        if item.material != material:
            continue
        rows, cols = np.divmod(item.cells, GRID.ncols)
        for row, col, base in zip(rows, cols, item.base, strict=True):
            above = float(start[row, col]) - float(base)
            if above > outcome_threshold():
                found.append(above)
    return math.fsum(found) * CELL_M2


class StockpileUnitsTest(unittest.TestCase):
    """CE-016-07, RF-016-09, RF-011-14, RF-011-16: la cubicación de la 011 con la base y el espesor de la detección."""

    outcome: ClassVar[Any]
    survey: ClassVar[np.ndarray]
    whole: ClassVar[Cubication]
    ground: ClassVar[Cubication]

    @classmethod
    def setUpClass(cls) -> None:
        job = ops.survey_job(flat=False)
        cls.survey = job.surface
        cls.outcome = stockpiles.detect_stockpiles(job)
        folder = cls.enterClassContext(project_tmp("gb-su-"))
        cls.whole = Cubication(folder, cls.outcome, cls.survey, tag="a")
        composed = np.where(np.isnan(cls.outcome.ground_grid()), cls.survey, cls.outcome.ground_grid())
        cls.ground = Cubication(folder, cls.outcome, composed, tag="b")
        cls.folder = folder

    def assertRelative(self, found: float, wanted: float, what: str = "") -> None:  # noqa: N802
        self.assertGreater(wanted, 0.0, what)
        self.assertLessEqual(abs(found - wanted) / wanted, TOLERANCE, f"{what}: {found!r} frente a {wanted!r}")

    def volume_of(self, material: str) -> float:
        """El volumen de la detección de ``material``: la suma de los de sus acopios (``Stockpile.volume_m3``)."""
        return math.fsum(item.volume_m3 for item in self.outcome.stockpiles if item.material == material)

    def test_each_material_is_one_unit_with_the_volume_of_the_detection(self) -> None:
        """CE-016-07, RF-016-09, RF-011-14: con dos materiales, **dos unidades antrópicas** (más la del terreno), cada una con el
        volumen de la detección de su material a ≤ 10⁻⁹ relativo —el de la detección y el calculado a mano celda a celda— y
        las tres suman el desmonte; el Acopio 5, con su base propia, está en la de «mineral»; leído por bandas de 32 filas (que
        parten las huellas) o de una vez, lo mismo."""
        self.assertEqual(self.outcome.materials, (MINERAL, WASTE))
        self.assertEqual([(unit.code, unit.kind.value) for unit in self.whole.column.units],
                         [("acopio_mineral", "anthropic"), ("acopio_esteril", "anthropic"), ("terreno", "natural")])
        self.assertEqual([item.base_surface for item in self.outcome.stockpiles if item.material == MINERAL],
                         [None, None, sdata.PREVIOUS_LABEL])
        once = Cubication(self.folder, self.outcome, self.survey, tag="c", band_rows=GRID.nrows)
        for material in (MINERAL, WASTE):
            code = CODES[material]
            with self.subTest(material=material):
                self.assertRelative(self.whole.volume(code), self.volume_of(material), "la detección")
                self.assertRelative(self.whole.volume(code), hand_volume(self.outcome, self.survey, material), "a mano")
                self.assertRelative(once.volume(code), self.volume_of(material), "de una vez")
        total = math.fsum(float(volume) for volume in self.whole.result.kernel.unit_volume_m3[kernel.ALL])
        self.assertRelative(total, self.whole.result.cut_m3, "las unidades suman el desmonte")
        self.assertRelative(self.whole.result.cut_m3, once.result.cut_m3, "el desmonte, por bandas")

    def test_the_cells_of_the_unit_are_those_of_the_footprint(self) -> None:
        """CE-016-07, RF-016-09, D-17: el umbral de presencia de la 011 es el de la huella, así que la unidad está **donde está la
        huella** (las celdas de su espesor sobre el umbral: aquí, todas) y ausente en el resto de la rejilla: su área es la de
        las huellas de su material, la ausente es el resto del desmonte, y esa parte es «sin dato» de su base (las rejillas son
        dispersas: la 011 la cuenta como tal sin avisar); ni cruces ni espesores negativos."""
        cut = self.whole.result.kernel.area_m2[kernel.ALL]
        self.assertEqual(float(cut), GRID.ncols * GRID.nrows * CELL_M2, "toda la rejilla tiene dato y se desmonta")
        for material in (MINERAL, WASTE):
            code = CODES[material]
            cells = np.concatenate([item.cells for item in self.outcome.stockpiles if item.material == material])
            thickness = np.concatenate([item.thickness for item in self.outcome.stockpiles if item.material == material])
            footprint = float(np.count_nonzero(thickness > outcome_threshold())) * CELL_M2
            with self.subTest(material=material):
                self.assertEqual(np.unique(cells).size, cells.size, "las celdas de dos acopios no se repiten")
                self.assertEqual(float(cells.size) * CELL_M2, math.fsum(item.area_m2 for item in self.outcome.stockpiles
                                                                       if item.material == material))
                self.assertEqual(footprint, float(cells.size) * CELL_M2, "ningún hueco: toda la huella pasa del umbral")
                self.assertEqual(float(cut) - self.whole.area("absent", code), footprint)
                self.assertEqual(self.whole.area("absent", code), float(cut) - footprint)
                self.assertEqual(self.whole.area("nodata", code), float(cut) - footprint, "ausente por falta de dato")
                self.assertEqual(self.whole.area("crossed", code), 0.0)
                base = self.outcome.base_grid(material)
                self.assertEqual(int(np.count_nonzero(np.isfinite(base))), cells.size, "la base solo tiene dato en la huella")
        self.assertEqual(self.whole.area("absent", GROUND), 0.0, "el terreno está en todas partes")

    def test_no_other_unit_has_volume_above_the_base_in_the_footprints(self) -> None:
        """CE-016-07, RF-016-09: **0 m³ de las demás unidades por encima de la base en las huellas**. Con el terreno sin acopios
        (``mín(z, base)`` en las huellas, la superficie fuera: lo que compone R-18) como partida, las unidades de los acopios
        valen 0 m³ y la del terreno es **la misma** que con los acopios encima: no recibe nada por encima de la base; y el desmonte
        con los acopios es el de sin ellos más el volumen de la detección."""
        for material in (MINERAL, WASTE):
            self.assertEqual(self.ground.volume(CODES[material]), 0.0, f"sin acopios, ninguno de {material}")
        self.assertRelative(self.whole.volume(GROUND), self.ground.volume(GROUND), "el terreno, con y sin los acopios encima")
        detected = math.fsum(self.volume_of(material) for material in (MINERAL, WASTE))
        self.assertRelative(self.whole.result.cut_m3 - self.ground.result.cut_m3, detected, "el desmonte de más es la detección")
        for material, other in ((MINERAL, WASTE), (WASTE, MINERAL)):
            self.assertRelative(self.whole.volume(CODES[material]), self.volume_of(material),
                                f"ningún volumen de {other} en las huellas de {material}")

    def test_a_loose_stockpile_weighs_v_rho_over_k(self) -> None:
        """CE-016-07, RF-016-09, RF-011-16 (error 67): cada unidad de acopio se pesa **suelta**, ``V·ρ/K`` toneladas con el volumen
        de la detección de su material y su densidad y su K; con la densidad in situ (``V·ρ``) pesaría K veces más. El terreno,
        in situ, ``V·ρ``; con dos materiales, dos filas de acopio con sus toneladas y el total de toneladas es la suma."""
        weighed = self.whole.weighed()
        found = {}
        for material in (MINERAL, WASTE):
            density, swell = SYNTHETIC[material]
            row = weighed.result.row(CODES[material])
            found[material] = row.mass_t
            self.assertRelative(row.volume_m3, self.volume_of(material), f"el volumen de {material}")
            self.assertRelative(row.mass_t, self.volume_of(material) * density / swell, f"V·ρ/K de {material}")
            self.assertGreater(abs(row.mass_t - self.volume_of(material) * density) / row.mass_t, 0.1, "no es V·ρ")
        in_situ = Cubication(self.folder, self.outcome, self.survey, tag="d",
                             states={MINERAL: materials.State.IN_SITU, WASTE: materials.State.IN_SITU}).weighed()
        for material in (MINERAL, WASTE):
            density, swell = SYNTHETIC[material]
            self.assertRelative(in_situ.result.row(CODES[material]).mass_t / found[material], swell, f"K de {material}")
        ground_row = weighed.result.row(GROUND)
        self.assertRelative(ground_row.mass_t, self.whole.volume(GROUND) * SYNTHETIC[GROUND][0], "el terreno, V·ρ")
        self.assertRelative(weighed.result.total.total_t, math.fsum([*found.values(), ground_row.mass_t]), "el total")
        self.assertEqual(weighed.result.missing, ())

    def test_one_material_is_one_unit(self) -> None:
        """CE-016-07, RF-016-09, D-19: con **un** solo material (los cinco acopios de «mineral»), **una** unidad de acopio con la
        suma de los volúmenes de la detección (más la del terreno): las unidades siguen a los materiales de la detección."""
        marks = tuple(dataclasses.replace(mark, material=MINERAL) for mark in ops.survey_marks(flat=False))
        job = dataclasses.replace(ops.survey_job(flat=False), marks=marks)
        outcome = stockpiles.detect_stockpiles(job)
        self.assertEqual(outcome.materials, (MINERAL,))
        one = Cubication(self.folder, outcome, job.surface, tag="e")
        self.assertEqual(one.column.codes, ("acopio_mineral", "terreno"))
        self.assertRelative(one.volume("acopio_mineral"), math.fsum(item.volume_m3 for item in outcome.stockpiles))
        self.assertRelative(one.volume("acopio_mineral"), hand_volume(outcome, job.surface, MINERAL), "a mano")

    def test_the_detection_gives_no_tonnes_of_its_own(self) -> None:
        """RF-016-09 (errores 52, 63 y 67: una sola cubicación): la detección da **volúmenes y áreas**, nunca toneladas: ninguna
        de sus cifras es de toneladas ni de densidad, ni lo es ninguna columna de la tabla de acopios o de candidatos, ni lo
        lleva el ``Stockpile`` que calcula."""
        units = {figure.unit for figure in design_provenance.STOCKPILE_FIGURES}
        self.assertEqual(units & {"t", "t/m3", "kg"}, set())
        for figure in design_provenance.STOCKPILE_FIGURES:
            self.assertNotRegex(figure.key, r"(mass|tonn|density|swell|_t$)", figure.key)
        for columns in (design_store.STOCKPILE_COLUMNS, design_store.CANDIDATE_COLUMNS):
            for column in columns:
                self.assertNotRegex(column.name, r"(mass|tonn|density|swell|_t$)", column.name)
        fields = {field.name for field in dataclasses.fields(stockpiles.Stockpile)}
        self.assertEqual({name for name in fields if "mass" in name or "tonn" in name or "density" in name}, set())


if __name__ == "__main__":
    unittest.main()
