# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H1 de la spec 013 (T20): E1 a E4 de principio a fin **sin Blender**, con las funciones del
dominio tal como las llamarán las órdenes (``design.steps``: la vista previa y «Calcular»; la
``Calculation``: «Crear»; ``core.provenance.recompute`` y ``core.versions.reproduce``), sobre el
proyecto del diseño (V01 con las máscaras al día; V02 sin compilar).

Una sola historia, en el orden de las pruebas (el proyecto es de la clase, como en
``VersionsStoryTest``), con los perfiles ``EXPL_10_60_6`` (10 m, 60°, berma de 6 m, ancla de 125 m)
y ``REST_5_35_6`` (5 m, 35°, berma de 6 m, ancla de 125 m) declarados en el proyecto. Cada número
que sale se compara con un cálculo a mano o con las rejillas leídas de nuevo del proyecto, no con
lo que devuelve la función que lo calculó:

- **a** (E5, RF-013-03): la vista previa de V01 dice las semillas y el dominio que salen de la
  cuenta de celdas del sitio, y no escribe nada; la de V02, sin máscaras, lo dice y no calcula.
- **b** (E1; CE-013-01): el hueco que sube desde un fondo a 630 m (envolvente ascendente *chamfer*
  5×5 con el talud general de ``EXPL_10_60_6``): «Calcular» no registra nada y «Crear» lo registra
  todo; la cota de cada celda al este del fondo es ``630 + k·paso·tan·0,98644`` (a ≤ 10⁻⁹ m).
- **c** (E1; CE-013-03): el escalonado de corte con ``EXPL_10_60_6``: bermas en ``125 + 10·n``,
  corte por encima de la envolvente con menos de un banco de diferencia, volumen a mano, caras
  dentro de la cara más la tolerancia, la rejilla de bermas y su tabla.
- **d** (E2; CE-013-01): la envolvente descendente euclídea exacta desde el terreno en el borde
  interior del límite legal es, en cada celda, ``650 − tan·d`` con ``d`` la distancia mínima entre
  centros de celda (≤ 10⁻⁹ relativo, cálculo manual por fuerza bruta); el *chamfer* de la
  ascendente difiere de la exacta ≤ 1,4 % (RF-013-12).
- **e** (E3; CE-013-03): el relleno de berma primero con ``REST_5_35_6`` de una montera de
  semillas de una capa: relleno por debajo de la envolvente con menos de un banco, volumen a mano.
- **f** (E4; CE-013-04, V02): el hueco con el talud general máximo de 10,6° en el sector 2
  (ADOPTADO, solo en V02): sus máscaras se compilan antes por pasos; la berma impuesta es
  ``5/tan 10,6° − 5/tan 35° = 19,5765237 m`` (≤ 10⁻⁹ relativo) y las anchuras medidas en la rejilla
  coinciden con ella dentro de una celda y con 6 m en el resto; ninguna inclinación pasa de la cara
  más la tolerancia (CE-013-04, CE-013-05). V01 no cambió.
- **g** (CE-013-08): congelar V01.r1, cambiar el ancla de ``EXPL_10_60_6`` solo en V01 y «recalcular
  lo obsoleto» repite solo el escalonado de corte; lo congelado no cambia y la comparación de
  magnitud usa la revisión congelada.
- **h** (CE-013-08, RF-009-11): reproducir V01.r1 da, sin escribir en el proyecto, las mismas
  salidas con el mismo hash y las mismas cifras.
- **i** (CE-013-08, D-25): congelar V01 otra vez y reproducir V01.r2 repite el escalonado
  recalculado con lo anterior con que se comparó (V01.r1), sin tenerla a mano.
- **j** (CE-013-06; E4): «Verificar un diseño por recinto…» (012) de las superficies de diseño de
  V01 y de V02 da 0 m³ en todos los recintos, y una celda movida en la torre hace fallar ese recinto.
- **k** (CE-013-06, RF-013-05): un sector sin búsqueda de intocables vigente se enseña en la vista
  previa y el cálculo se niega, sin dejar nada.
- **l** (CE-013-06): al cambiar una restricción, las operaciones y la superficie quedan
  obsoletas con su causa.

Los casos de referencia con sus tolerancias están en ``test_ref_envelopes`` (CE-013-01 y 02),
``test_ref_benching`` (CE-013-03, 04 y 05), ``test_ref_design_masks`` (CE-013-06) y ``test_ref_pit``
(CE-013-09): el hito los exige en verde (T20), y esta historia añade que las funciones, llamadas
como las llamarán las órdenes, dan lo mismo sobre el proyecto.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design.test_store import (
    BY_HAND,
    FILL_PROFILE,
    FILL_VALUES,
    PROFILE,
    SURFACE,
    declare_profile,
    design_request,
    envelope_request,
    last,
    real_definitions,
)
from tests.support.versions_fixtures import change_counter, files

steps = import_geoblender("design.steps")
benching = import_geoblender("design.benching")
compose = import_geoblender("design.compose")
design_model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_provenance = import_geoblender("design.provenance")
design_sectors = import_geoblender("design.sectors")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
access = import_geoblender("gis.masks.access")
geotiff_reader = import_geoblender("gis.geotiff.reader")
raster_mod = import_geoblender("gis.raster")
freeze = import_geoblender("core.versions.freeze")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
stale = import_geoblender("core.provenance.stale")
graph = import_geoblender("core.provenance.graph")
versions_check = import_geoblender("core.versions.check")
versions_read = import_geoblender("core.versions.read")
res_provenance = import_geoblender("reserves.provenance")
cstore = import_geoblender("reserves.compliance_store")
compliance = import_geoblender("reserves.compliance")
surfaces = import_geoblender("reserves.surfaces")

SCALE = oracles.CHAMFER_SCALE
"""El factor del *chamfer* 5×5 (ADR-0014): una pared alineada con la rejilla queda un 1,356 %
corta."""
STEP_M = 2.0
"""El paso de la rejilla del sitio (m)."""
SECTOR_SLOPE = "des.sector.sector_2.max_general_slope_deg"
BOTTOM_M = 630.0
"""El fondo del hueco de E1 y E4 (m)."""
TOLERANCE_FACE_DEG = 1.0
"""La tolerancia de cara por defecto (``des.tolerance.face_deg``)."""
SECTOR_SLOPE_DEG = 10.6
"""El talud general máximo del sector 2 de E4 (decisión de la propiedad)."""
START_Z = cfx.START_Z
NEW_ANCHOR_M = 127.0
"""El ancla nueva de ``EXPL_10_60_6`` en V01 (m)."""
MOUND_TOP_M = 660.0
"""La cota de la montera de E3 (m)."""
PROFILE_HEIGHT = 10.0
"""La altura de banco de ``EXPL_10_60_6`` (m)."""
PROFILE_ANCHOR = 125.0
"""Su cota de ancla (m)."""


def tan_deg(degrees: float) -> float:
    return math.tan(math.radians(degrees))


def general_deg(height: float, face_deg: float, berm: float) -> float:
    """El talud general (°) de un perfil, a mano: ``atan(h / (h/tan α + B))``."""
    return math.degrees(math.atan(height / (height / tan_deg(face_deg) + berm)))


EXPL_GENERAL_DEG = general_deg(10.0, 60.0, 6.0)
REST_GENERAL_DEG = general_deg(5.0, 35.0, 6.0)
IMPOSED_BERM_M = 5.0 / tan_deg(SECTOR_SLOPE_DEG) - 5.0 / tan_deg(35.0)
"""La berma del sector de 10,6° con ``REST_5_35_6``, a mano (19,5765237 m)."""


def col_of(x_local: float) -> int:
    """La columna de la celda cuyo centro está en ``x`` local (m): el sitio parte de x = −20."""
    return int(round((x_local + 20.0) / STEP_M - 0.5))


def row_of(y_local: float) -> int:
    """La fila de la celda cuyo centro está en ``y`` local (m): el sitio parte de y = 220."""
    return int(round((220.0 - y_local) / STEP_M - 0.5))


def never(request: Any) -> Iterator[Any]:
    raise AssertionError("la historia del hito H1 no recalcula ni reproduce una verificación")


def des_state(project: Any, root: Path) -> dict[str, Any]:
    """Lo que ``des`` ha dejado en un proyecto: operaciones, datos, tablas, cifras y ficheros."""
    with project.read() as conn:
        def query(sql: str) -> list[Any]:
            return conn.execute(sql).fetchall()

        return {
            "operations": query("SELECT uid, status FROM gb_operation WHERE op_type LIKE "
                                "'des.%' ORDER BY fid"),
            "datasets": query("SELECT name FROM gb_dataset WHERE name LIKE 'des!_%' ESCAPE '!' "
                              "ORDER BY name"),
            "tables": query("SELECT name FROM sqlite_master WHERE name LIKE 'des!_%' ESCAPE '!' "
                            "ORDER BY name"),
            "figures": query("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"),
            "files": sorted(path.name for path in (root / "rasters").iterdir())}


def incline_pairs(grid: np.ndarray, inside: np.ndarray) -> float:
    """La mayor inclinación (°) entre celdas vecinas a 8 vecinos que están **las dos** en
    ``inside`` (paso de 2 m)."""
    worst = 0.0
    rows, cols = grid.shape
    for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
        first = (slice(0, rows - d_row), slice(max(0, -d_col), cols - max(0, d_col)))
        second = (slice(d_row, rows), slice(max(0, d_col), cols - max(0, -d_col)))
        both = inside[first] & inside[second]
        rise = np.abs(grid[first] - grid[second]) / (STEP_M * math.hypot(d_row, d_col))
        if both.any():
            worst = max(worst, float(rise[both].max()))
    return math.degrees(math.atan(worst))


def moved_incline(grid: np.ndarray, moved: np.ndarray) -> float:
    """La mayor inclinación (°) de una celda con movimiento a cualquiera de sus 8 vecinas (paso de
    2 m): lo que mide el informe, recalculado aparte."""
    rows, cols = grid.shape
    padded = np.pad(grid, 1, constant_values=np.nan)
    worst = 0.0
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row == 0 and d_col == 0:
                continue
            side = padded[1 + d_row:1 + d_row + rows, 1 + d_col:1 + d_col + cols]
            with np.errstate(invalid="ignore"):
                rise = np.abs(grid - side) / (STEP_M * math.hypot(d_row, d_col))
            pick = moved & np.isfinite(rise)
            if pick.any():
                worst = max(worst, float(rise[pick].max()))
    return math.degrees(math.atan(worst))


class FlowTest(dfx.DesignProjectCase):
    """E1 a E4 de principio a fin (véase el módulo)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(
            *real_definitions(), cstore.operation_def(never, cstore.REPRODUCE[cstore.VERIFY]),
            *cstore.FIGURES))
        declare_profile(cls.project, cls.clock, PROFILE)
        declare_profile(cls.project, cls.clock, FILL_PROFILE, **FILL_VALUES)
        cls.masks1 = access.load_masks(cls.project, cls.v1.uid)
        cls.start = np.array(cfx.site_start().values, dtype=np.float64)
        cls.area = float(cls.masks1.grid.cell_area)
        cls.made: dict[str, Any] = {}

    # --- Ayudas -------------------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Lo que ``des`` ha dejado en el proyecto de la historia."""
        return des_state(self.project, self.root)

    def calculate_envelope(self, request: Any, version: Any = None, **kw: Any) -> Any:
        """«Calcular» una envolvente (``design.steps.envelope_run``): la ``Calculation``."""
        target = self.v1 if version is None else version
        if target is self.v1:
            kw.setdefault("masks", self.masks1)
        return last(steps.envelope_run(self.project, request, version=target.uid, **kw)).result

    def calculate_design(self, request: Any, version: Any = None, **kw: Any) -> Any:
        """«Calcular» un escalonado sobre la superficie de partida del sitio."""
        target = self.v1 if version is None else version
        if target is self.v1:
            kw.setdefault("masks", self.masks1)
        return last(steps.design_run(self.project, request, SURFACE, version=target.uid,
                                     **kw)).result

    def create(self, calculation: Any) -> Any:
        """«Crear»: lo registra (una transacción) un minuto después."""
        self.clock.advance(minutes=1)
        return calculation.create()

    def grid_of(self, family: str, name: str, version: Any = None) -> np.ndarray:
        """Las celdas de la rejilla ``family`` de la operación ``name`` tal como están en el
        proyecto."""
        record = self.record(design_provenance.dataset_name(family, name),
                             self.v1 if version is None else version)
        return np.array(geotiff_reader.read_geotiff(self.root / record.locator).values,
                        dtype=np.float64)

    def figures_of(self, uid: str) -> dict[str, float]:
        return {key: value for key, value in self.query(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def report_codes(self, name: str, version: Any = None) -> list[str]:
        """Los códigos de los avisos y notas del informe del escalonado ``name``."""
        target = self.v1 if version is None else version
        table = design_provenance.dataset_locator(design_provenance.REPORT_TABLE, name,
                                                  target.code)
        rows = self.query(f'SELECT quantity, note FROM "{table}" ORDER BY fid')
        return [json.loads(note)["code"] for quantity, note in rows
                if quantity in ("warning", "note")]

    def berm_rows(self, name: str, version: Any = None) -> list[tuple[Any, ...]]:
        target = self.v1 if version is None else version
        table = design_provenance.dataset_locator(design_provenance.BERM_TABLE, name, target.code)
        return self.query(f'SELECT sector, profile, level_m, cells, area_m2, anchor_m, '
                          f'anchor_diff_m FROM "{table}" ORDER BY fid')

    # --- E5: la vista previa --------------------------------------------------------------------

    def test_a_the_preview_of_v01_counts_the_cells_and_writes_nothing(self) -> None:
        """RF-013-03, RNF-013-06 (E5): V01 (con las máscaras al día) dice las semillas del fondo
        (el sector 1: 35 × 80 celdas de 2 m), el dominio de trabajo (el perímetro de actuación y la
        franja de solo relleno: 8.540 celdas) y los dos sectores que toca, sin avisos; V02, sin
        compilar, dice que faltan las máscaras y no da semillas; ninguna escribe nada."""
        before = self.state()
        request = self.pit_request()
        summary = last(steps.preview_steps(self.project, request, self.v1.uid)).result
        self.assertEqual(summary.version, "V01")
        self.assertEqual(summary.masks_state, access.MaskState.CURRENT)
        self.assertEqual((summary.seeds.cells, summary.seeds.area_m2), (35 * 80, 35 * 80 * 4.0))
        self.assertEqual((summary.seeds.min_m, summary.seeds.max_m), (BOTTOM_M, BOTTOM_M))
        self.assertEqual(summary.seeds.outside_domain, 0)
        self.assertEqual(summary.domain.cells, 8540)
        self.assertEqual([(s.code, s.touched, s.pending) for s in summary.sectors],
                         [("sector_1", True, False), ("sector_2", True, False)])
        self.assertEqual(summary.warnings("es"), ())
        lines = summary.lines("es")
        self.assertTrue(any("630" in line for line in lines), lines)
        other = last(steps.preview_steps(self.project, request, self.v2.uid)).result
        self.assertEqual(other.masks_state, access.MaskState.MISSING)
        self.assertIsNone(other.seeds)
        self.assertEqual(len(other.warnings("es")), 1, other.lines("es"))
        self.assertEqual(self.state(), before, "la vista previa solo lee")
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.MISSING)

    # --- E1: el hueco que sube desde un fondo --------------------------------------------------

    def pit_request(self, name: str = "Hueco", **changes: Any) -> Any:
        """El hueco de E1: semillas a 630 m en el sector 1 y envolvente ascendente con el talud
        general de ``EXPL_10_60_6`` (*chamfer* 5×5)."""
        base: dict[str, Any] = {
            "direction": "up", "slope_deg": EXPL_GENERAL_DEG, "metric": "chamfer5",
            "seeds": design_model.SeedSource("fixed", elevation_m=BOTTOM_M,
                                             zone=design_model.Zone("sector", "sector_1"))}
        return envelope_request(name, **{**base, **changes})

    def test_b_the_pit_envelope_is_calculated_then_created(self) -> None:
        """RF-013-11, RF-013-12, RF-013-17, RF-013-33, D-14, CE-013-01 (E1): «Calcular» deja la
        envolvente en un temporal y no registra nada; «Crear» la registra (una operación hecha, su
        rejilla y sus cifras). La cota al este del fondo, en la misma fila, es
        ``630 + k·2·tan·0,98644`` (la pared alineada con la rejilla del *chamfer* 5×5), a ≤ 10⁻⁹ m;
        el fondo queda a 630 m y la envolvente es la de las 8.540 celdas del dominio."""
        before = self.state()
        calculation = self.calculate_envelope(self.pit_request())
        self.assertTrue(calculation.open)
        after = self.state()
        self.assertEqual({k: v for k, v in after.items() if k != "files"},
                         {k: v for k, v in before.items() if k != "files"},
                         "calcular no registra nada")
        self.assertEqual(len(after["files"]), len(before["files"]) + 1, "solo el temporal")
        stored = self.create(calculation)
        self.assertFalse(calculation.open)
        self.made["pit"] = stored
        self.assertEqual(self.state()["files"], sorted(before["files"] + ["des_env_hueco_v01.tif"]))
        self.assertEqual(self.query("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                                    stored.handle.uid), [("des.envelope", "done")])
        self.assertEqual(stored.handle.version_uid, self.v1.uid)
        env = self.grid_of("env", "Hueco")
        finite = np.isfinite(env)
        self.assertEqual(int(finite.sum()), 8540)
        self.assertEqual(float(np.nanmin(env)), BOTTOM_M)
        seeds = np.zeros(env.shape, dtype=bool)
        seeds[row_of(179.0):row_of(21.0) + 1, col_of(21.0):col_of(89.0) + 1] = True
        self.assertEqual(int(seeds.sum()), 2800)
        self.assertTrue(np.all(env[seeds] == BOTTOM_M))
        tan = tan_deg(EXPL_GENERAL_DEG)
        for y in (60.0, 101.0, 139.0):
            row = row_of(y)
            for k in range(1, 41):
                expected = BOTTOM_M + k * STEP_M * tan * SCALE
                self.assertAlmostEqual(env[row, col_of(89.0) + k], expected, delta=1e-9,
                                       msg=f"fila y={y}, {k} celdas al este del fondo")
        figures = self.figures_of(stored.handle.uid)
        self.assertEqual((figures["des.env_cells"], figures["des.env_min_m"]), (8540, BOTTOM_M))
        self.assertAlmostEqual(figures["des.env_max_m"], float(np.nanmax(env)), delta=1e-9)
        self.assertNotIn("des.env_cut_m3", figures, "unas semillas de cota fija no tienen partida")

    # --- E1: el escalonado de corte ------------------------------------------------------------

    def moved_volume(self, start: np.ndarray, design: np.ndarray, sign: float) -> float:
        """El volumen (m³) que se desmonta (``sign`` = 1) o se rellena (−1) entre ``start`` y
        ``design``, a mano, en las celdas que mueven más del espesor mínimo de la 012."""
        thickness = float(res_provenance.VERIFY_MIN_THICKNESS_DEF.default)
        moved = sign * (start - design)
        return float(np.sum(moved[moved > thickness]) * self.area)

    def test_c_the_pit_is_stepped_in_cut_with_expl_10_60_6(self) -> None:
        """RF-013-22, RF-013-26, RF-013-28, RF-013-31, CE-013-03 (E1): el escalonado de corte con
        ``EXPL_10_60_6``: las bermas en ``125 + 10·n``; el corte por encima de la envolvente, con
        menos de un banco de diferencia, y nunca por encima del terreno; el desmonte, el de las
        celdas leídas de nuevo; la rejilla de bermas y su tabla cuadran; ninguna cara pasa de 60°
        más la tolerancia."""
        request = design_request("Bancos del hueco", envelope="Hueco", sense="cut",
                                 base_profile=PROFILE)
        before = self.state()
        calculation = self.calculate_design(request)
        after = self.state()
        self.assertEqual({k: v for k, v in after.items() if k != "files"},
                         {k: v for k, v in before.items() if k != "files"},
                         "calcular no registra nada")
        stored = self.create(calculation)
        self.made["pit_design"] = stored
        design = self.grid_of("srf", "Bancos del hueco")
        env = self.grid_of("env", "Hueco")
        brm = self.grid_of("brm", "Bancos del hueco")
        self.assertFalse(np.isnan(design).any(), "la superficie de diseño no tiene huecos")
        self.assertTrue(np.all(design <= self.start), "el corte nunca sube el terreno")
        moved = self.start - design > 0.02
        self.assertGreater(int(moved.sum()), 2000)
        both = moved & np.isfinite(env)
        self.assertTrue(np.array_equal(both, moved), "solo se mueve donde hay envolvente")
        gap = design[moved] - env[moved]
        self.assertGreaterEqual(float(gap.min()), -1e-9, "el corte queda por encima de S")
        self.assertLess(float(gap.max()), 10.0 + 1e-9, "con menos de un banco de diferencia")
        figures = self.figures_of(stored.handle.uid)
        cut = self.moved_volume(self.start, design, 1.0)
        self.assertAlmostEqual(figures["des.cut_m3"] / cut, 1.0, delta=1e-9)
        self.assertEqual(figures["des.fill_m3"], 0.0)
        self.assertGreater(cut, 100_000.0)
        finite = np.isfinite(brm)
        levels = (brm[finite] - PROFILE_ANCHOR) / PROFILE_HEIGHT
        self.assertLessEqual(float(np.abs(levels - np.round(levels)).max()) * PROFILE_HEIGHT, 1e-9,
                             "las bermas están en 125 + 10·n")
        self.assertTrue(np.array_equal(design[finite], brm[finite]))
        rows = self.berm_rows("Bancos del hueco")
        self.assertEqual(len(rows), figures["des.berm_count"])
        self.assertEqual(sum(row[3] for row in rows), int(finite.sum()))
        for sector, profile, level, cells, area, anchor, diff in rows:
            self.assertEqual(profile, PROFILE)
            self.assertAlmostEqual((level - PROFILE_ANCHOR) / PROFILE_HEIGHT,
                                   round((level - PROFILE_ANCHOR) / PROFILE_HEIGHT), delta=1e-9)
            self.assertEqual(area, cells * self.area)
            self.assertLessEqual(abs(diff), 1e-6)
        inside = self.inside(env, "cut")
        worst = incline_pairs(design, inside)
        self.assertLessEqual(worst, 60.0 + TOLERANCE_FACE_DEG)
        self.assertGreater(worst, 45.0, "la prueba mira las caras de verdad")
        self.assertIn("des.magnitude_no_reference", self.report_codes("Bancos del hueco"),
                      "la primera vez no hay revisión con que comparar")
        self.assertIn("des.slope_over_face", self.report_codes("Bancos del hueco"))
        self.assertAlmostEqual(figures["des.slope_max_deg"], moved_incline(design, moved),
                               delta=1e-9)
        self.assertGreater(figures["des.slope_max_deg"], 80.0,
                           "contra lo prohibido (la cuneta) hay un escalón, y el informe lo dice")
        self.assertGreater(figures["des.edge_step_max_m"], 10.0)

    def inside(self, env: np.ndarray, sense: str, version: Any = None) -> np.ndarray:
        """Las celdas del dominio de trabajo (donde hay envolvente) que la composición admite
        (``sense``): las parejas de vecinas que están las dos aquí son las que miden las caras (el
        borde de lo prohibido es un escalón, aviso aparte)."""
        masks = self.masks1 if version is None or version is self.v1 else self.masks(version)
        return compose.allowed_cells(masks, sense) & np.isfinite(env)

    # --- E2: el hueco que baja desde el límite legal -------------------------------------------

    def test_d_the_exact_envelope_from_the_legal_limit_is_the_hand_distance(self) -> None:
        """RF-013-01, RF-013-12, RF-013-14, CE-013-01 (E2): las semillas son el terreno (650 m) en
        el borde interior del límite legal (1.900 celdas) y la envolvente descendente euclídea exacta
        vale, en cada celda, ``650 − tan 35°·d`` con ``d`` la distancia mínima entre centros de
        celda a las semillas (fuerza bruta, ≤ 10⁻⁹ relativo); el desmonte frente al terreno es el
        de las celdas; y el *chamfer* de la ascendente difiere de la exacta ≤ 1,4 %."""
        request = envelope_request(
            "Hueco bajo el limite", direction="down", slope_deg=35.0, metric="exact",
            seeds=design_model.SeedSource("surface", surface=SURFACE,
                                          zone=design_model.Zone("constraint", "concesion:inner")))
        calculation = self.calculate_envelope(request)
        self.assertEqual(calculation.seeds.cells, 1900)
        stored = self.create(calculation)
        self.made["bowl"] = stored
        env = self.grid_of("env", "Hueco bajo el limite")
        band = self.masks1.zone("concesion:inner").mask(env.shape)
        self.assertEqual(int(band.sum()), 1900)
        self.assertTrue(np.all(env[band & np.isfinite(env)] == START_Z))
        rows, cols = np.nonzero(np.isfinite(env))
        seed_rows, seed_cols = np.nonzero(band)
        worst = 0.0
        for first in range(0, rows.size, 1000):  # fuerza bruta en todas las celdas, por trozos
            chunk = slice(first, first + 1000)
            distance = np.hypot(rows[chunk, None] - seed_rows[None, :],
                                cols[chunk, None] - seed_cols[None, :]).min(axis=1) * STEP_M
            measured = (START_Z - env[rows[chunk], cols[chunk]]) / tan_deg(35.0)
            worst = max(worst, float(np.abs(measured - distance).max()))
            self.assertGreater(float(distance.max()), 0.0)
        self.assertLessEqual(worst, 1e-9 * 100.0, "d a 10⁻⁹ relativo de los 100 m más lejanos")
        figures = self.figures_of(stored.handle.uid)
        finite = np.isfinite(env)
        self.assertAlmostEqual(
            figures["des.env_cut_m3"] / float(np.sum(np.clip(self.start[finite] - env[finite],
                                                             0.0, None)) * self.area), 1.0,
            delta=1e-9)
        self.assertEqual(figures["des.env_fill_m3"], 0.0)
        exact = self.calculate_envelope(self.pit_request("Hueco exacto", metric="exact"))
        self.addCleanup(exact.discard)
        chamfer = self.grid_of("env", "Hueco")
        rise_c = (chamfer - BOTTOM_M) / tan_deg(EXPL_GENERAL_DEG)
        rise_e = (exact.outcome.grid - BOTTOM_M) / tan_deg(EXPL_GENERAL_DEG)
        far = np.isfinite(rise_e) & (rise_e > 0.0)
        self.assertTrue(far.any())
        self.assertLessEqual(float(np.abs(rise_c[far] / rise_e[far] - 1.0).max()), 0.014)
        self.assertGreater(float(np.abs(rise_c[far] / rise_e[far] - 1.0).max()), 0.005,
                           "las dos métricas no son la misma")
        self.assertIsNotNone(exact.outcome.envelope.reduction)

    # --- E3: el relleno de berma primero -------------------------------------------------------

    def flat_surface(self, value: float) -> Any:
        start = cfx.site_start()
        return raster_mod.Raster(start.grid, np.full(start.values.shape, value, dtype=np.float64),
                                 start.crs, start.vertical)

    def test_e_the_mound_is_filled_berm_first_with_rest_5_35_6(self) -> None:
        """RF-013-01, RF-013-02, RF-013-14, RF-013-23, CE-013-03 (E3): las semillas son las 25
        celdas de una capa de polígonos a 660 m en una superficie, el dominio se acota a otra capa y
        la envolvente descendente tiene como mucho 40 m de alcance; el relleno de berma primero con
        ``REST_5_35_6`` queda por debajo de la envolvente con menos de un banco de diferencia, por
        encima del terreno, con las bermas en ``125 + 5·n`` y el terraplén de las celdas."""
        self.write_surfaces(("montera", self.flat_surface(MOUND_TOP_M)))
        self.write_layer("gis_fea_montera", [[[cfx.rectangle(144.0, 56.0, 154.0, 66.0)]]])
        self.write_layer("gis_fea_ambito", [[[cfx.rectangle(100.0, 20.0, 190.0, 100.0)]]])
        request = envelope_request(
            "Montera", direction="down", slope_deg=REST_GENERAL_DEG, metric="chamfer5",
            reach_m=40.0,
            seeds=design_model.SeedSource("surface", surface="gis_dtm_montera",
                                          zone=design_model.Zone("layer", "gis_fea_montera")),
            domain=design_model.WorkDomain(layer="gis_fea_ambito"))
        calculation = self.calculate_envelope(request)
        self.assertEqual(calculation.seeds.cells, 25)
        self.assertEqual(calculation.seeds.outside_domain, 0)
        self.made["mound"] = self.create(calculation)
        env = self.grid_of("env", "Montera")
        tan = tan_deg(REST_GENERAL_DEG)
        row = row_of(61.0)
        last_seed = col_of(153.0)
        for k in range(1, 18):  # hasta x = 187 m: la capa del dominio acaba en 190 m
            self.assertAlmostEqual(env[row, last_seed + k],
                                   MOUND_TOP_M - k * STEP_M * tan * SCALE, delta=1e-9)
        far = np.isfinite(env)
        self.assertGreater(int(far.sum()), 400)
        self.assertEqual(float(np.nanmax(env)), MOUND_TOP_M)
        fill_request = design_request("Terraplen de la montera", envelope="Montera",
                                         sense="fill", base_profile=FILL_PROFILE)
        calculation = self.calculate_design(fill_request)
        stored = self.create(calculation)
        self.made["mound_design"] = stored
        design = self.grid_of("srf", "Terraplen de la montera")
        brm = self.grid_of("brm", "Terraplen de la montera")
        self.assertTrue(np.all(design >= self.start), "el relleno nunca baja el terreno")
        moved = design - self.start > 0.02
        self.assertGreater(int(moved.sum()), 100)
        under = env[moved] - design[moved]
        self.assertGreaterEqual(float(under.min()), -1e-9, "el relleno queda por debajo de S")
        self.assertLess(float(under.max()), 5.0 + 1e-9, "con menos de un banco de diferencia")
        figures = self.figures_of(stored.handle.uid)
        fill = self.moved_volume(self.start, design, -1.0)
        self.assertAlmostEqual(figures["des.fill_m3"] / fill, 1.0, delta=1e-9)
        self.assertEqual(figures["des.cut_m3"], 0.0)
        finite = np.isfinite(brm)
        self.assertTrue(finite.any())
        levels = (brm[finite] - 125.0) / 5.0
        self.assertLessEqual(float(np.abs(levels - np.round(levels)).max()) * 5.0, 1e-9)
        inside = self.inside(env, "fill")
        self.assertLessEqual(incline_pairs(design, inside), 35.0 + TOLERANCE_FACE_DEG)
        self.assertEqual(figures["des.berm_count"], len(self.berm_rows("Terraplen de la montera")))

    # --- E4: el frente tendido de un sector (V02) -----------------------------------------------

    def hashes(self) -> dict[str, str]:
        """El hash de contenido de cada dato de ``des`` y su estado, en todo el proyecto."""
        return {name: f"{status}:{sha}" for name, status, sha in self.query(
            "SELECT name, status, content_sha256 FROM gb_dataset WHERE name LIKE 'des!_%' "
            "ESCAPE '!' ORDER BY name")}

    def plateaus(self, row: np.ndarray, anchor: float, height: float, first: int, last: int
                 ) -> list[int]:
        """Las anchuras, en celdas, de los tramos planos de una fila en una cota ``anchor + n·h``
        (a ≤ 10⁻⁹ m) que están enteros entre las columnas ``first`` y ``last`` y limitados a los dos
        lados por celdas que no lo son."""
        levels = (row - anchor) / height
        flat = np.abs(levels - np.round(levels)) * height <= 1e-9
        found: list[int] = []
        column = first
        while column <= last:
            if flat[column] and not flat[column - 1]:
                end = column
                while end < flat.size and flat[end]:
                    end += 1
                if end <= last + 1 and end < flat.size and not flat[end]:
                    found.append(end - column)
                column = end
            else:
                column += 1
        return found

    def test_f_the_sector_with_a_general_slope_of_10_6_degrees_has_its_own_berm(self) -> None:
        """RF-013-04, RF-013-09, RF-013-13, RF-013-25, RF-013-26, CE-013-04, CE-013-05 (E4, V02):
        con el talud general máximo de 10,6° en el sector 2 (ADOPTADO, solo en V02: V01 no cambia)
        y las semillas de una capa en el hueco entre los dos sectores, «Calcular» compila antes las
        máscaras de V02 por pasos; la pendiente de la envolvente es la del sector en cada celda
        (``2·tan·0,98644`` entre vecinas, a ≤ 10⁻⁹ m); la berma impuesta es 19,5765237 m (a mano,
        ≤ 10⁻⁹ relativo) y las anchuras medidas en la rejilla coinciden con ella dentro de una celda
        en el sector 2 y con los 6 m del perfil en el sector 1; ninguna inclinación entre celdas
        pasa de la cara más la tolerancia, también entre sectores."""
        profile = design_model.BenchProfile(FILL_PROFILE, "REST_5_35_6", 5.0, 35.0, 6.0, 125.0)
        self.assertAlmostEqual(benching.sector_berm(profile, SECTOR_SLOPE_DEG) / IMPOSED_BERM_M,
                               1.0, delta=1e-9)
        self.assertAlmostEqual(IMPOSED_BERM_M, 19.5765237, delta=5e-8)
        self.assertEqual(benching.sector_berm(profile, None), 6.0)
        v1_before = self.hashes()
        stale_before = self.query("SELECT count(*) FROM gb_stale")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).create(
                conn, SECTOR_SLOPE, SECTOR_SLOPE_DEG, kind="ADOPTADO",
                reason="Decisión de la propiedad", version=self.v2.code, **BY_HAND)
        slopes = {version: {sector.code: sector.slope for sector in
                            design_sectors.design_sectors(self.project, version.uid)}
                  for version in (self.v1, self.v2)}
        self.assertIsNone(slopes[self.v1]["sector_2"], "el talud es solo de V02")
        self.assertEqual(slopes[self.v2]["sector_2"].value, SECTOR_SLOPE_DEG)
        self.assertIsNone(slopes[self.v2]["sector_1"])
        self.write_layer("gis_fea_fondo", [[[cfx.rectangle(92.0, 22.0, 108.0, 178.0)]]])
        request = envelope_request(
            "Frente tendido", direction="up", metric="chamfer5", slope_mode="sectors",
            slope_deg=None, base_profile=FILL_PROFILE,
            seeds=design_model.SeedSource("fixed", elevation_m=BOTTOM_M,
                                          zone=design_model.Zone("layer", "gis_fea_fondo")))
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.MISSING)
        calculation = self.calculate_envelope(request, self.v2)
        self.assertIs(access.mask_state(self.project, self.v2.uid)[0], access.MaskState.CURRENT)
        self.assertEqual(calculation.seeds.cells, 8 * 78)
        self.made["front"] = self.create(calculation)
        env = self.grid_of("env", "Frente tendido", self.v2)
        tan_rest, tan_front = tan_deg(REST_GENERAL_DEG), tan_deg(SECTOR_SLOPE_DEG)
        for y in (61.0, 101.0, 139.0):
            row = env[row_of(y)]
            for c in range(col_of(113.0), col_of(175.0)):  # el sector 2: de 110 a 180 m
                self.assertAlmostEqual(row[c + 1] - row[c], STEP_M * tan_front * SCALE,
                                       delta=1e-9)
            for c in range(col_of(25.0), col_of(89.0)):  # el sector 1: de 20 a 90 m
                self.assertAlmostEqual(row[c] - row[c + 1], STEP_M * tan_rest * SCALE,
                                       delta=1e-9)
        stairs = design_request("Frente tendido en bancos", envelope="Frente tendido",
                                sense="cut", base_profile=FILL_PROFILE)
        stored = self.create(self.calculate_design(stairs, self.v2))
        self.made["front_design"] = stored
        design = self.grid_of("srf", "Frente tendido en bancos", self.v2)
        self.assertTrue(np.all(design <= self.start))
        wide: list[int] = []
        narrow: list[int] = []
        for y in (61.0, 101.0, 139.0):
            row = design[row_of(y)]
            wide += self.plateaus(row, 125.0, 5.0, col_of(113.0), col_of(175.0))
            narrow += self.plateaus(row, 125.0, 5.0, col_of(23.0), col_of(87.0))
        self.assertGreaterEqual(len(wide), 3, wide)
        self.assertGreaterEqual(len(narrow), 3, narrow)
        for width in wide:
            self.assertLessEqual(abs(width * STEP_M - IMPOSED_BERM_M), STEP_M, wide)
        for width in narrow:
            self.assertLessEqual(abs(width * STEP_M - 6.0), STEP_M, narrow)
        inside = self.inside(env, "cut", self.v2)
        worst = incline_pairs(design, inside)
        self.assertLessEqual(worst, 35.0 + TOLERANCE_FACE_DEG)
        self.assertGreater(worst, 25.0, "la prueba mira las caras de verdad")
        self.assertTrue(set(v1_before.items()) <= set(self.hashes().items()), "V01 no cambió")
        self.assertEqual(self.query("SELECT count(*) FROM gb_stale"), stale_before)

    # --- Congelar, recalcular lo obsoleto y reproducir ------------------------------------------

    def frozen(self, revision_uid: str) -> dict[str, Any]:
        """Lo congelado por ``revision_uid``: la fila de la revisión y cada elemento."""
        return {
            "revision": self.query("SELECT state, snapshot_dir, snapshot_sha256, altered_at FROM "
                                   "gb_revision WHERE uid = ?", revision_uid),
            "items": self.query("SELECT item_kind, item_uid, part, item_rev, content_sha256, "
                                "copied, snapshot_path, snapshot_layer, file_sha256, file_size, "
                                "state FROM gb_revision_item WHERE revision_uid = ? ORDER BY "
                                "item_kind, item_uid", revision_uid)}

    def settings_of(self, uid: str) -> dict[str, Any]:
        return dict(json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?",
                                          uid)[0][0]))

    def test_g_freezing_v01_and_recomputing_what_became_stale(self) -> None:
        """CE-013-08, RF-013-17, RF-013-30, RF-008-26, D-25 (E6): V01.r1 congela las cuatro
        operaciones; cambiar el ancla de ``EXPL_10_60_6`` solo en V01 deja obsoleto solo el
        escalonado de corte (el resto no lee ese ancla) y «recalcular lo obsoleto» lo repite, sin
        pedir confirmación, en la revisión abierta: sus bermas están en ``127 + 10·n``, su desmonte
        cambia y se compara con el de V01.r1; la envolvente y lo demás no se tocan, y lo congelado
        tampoco."""
        design = self.made["pit_design"]
        self.made["figures"] = {name: self.figures_of(stored.handle.uid)
                                for name, stored in self.made.items()
                                if hasattr(stored, "handle")}
        self.clock.advance(minutes=1)
        outcome = last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega")).result
        self.made["r1"], self.made["r2"] = str(outcome.frozen.uid), str(outcome.opened.uid)
        with self.project.read() as conn:
            kept = Counter(item.key for item in versions_read.version_figures(conn, self.v1.uid))
        self.assertEqual((kept["des.env_cells"], kept["des.cut_m3"], kept["des.fill_m3"]),
                         (3, 2, 2), "V01.r1 congela las cifras de las 3 envolventes y los 2 escalonados")
        frozen = self.frozen(self.made["r1"])
        self.assertEqual(frozen["revision"][0][0], "frozen")
        before = self.hashes()
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).create(
                conn, design_params.bench_key(PROFILE, "anchor_m"), NEW_ANCHOR_M,
                kind="HIPÓTESIS", reason="Prueba del hito H1", version=self.v1.code, **BY_HAND)
        with self.project.read() as conn:
            plan = recompute_mod.plan_recompute(graph.load_graph(conn))
        self.assertEqual([unit.operations for unit in plan.units], [(design.handle.uid,)])
        self.clock.advance(minutes=1)
        done = last(recompute_mod.recompute_steps(self.project)).result
        self.assertEqual([item.status for item in done.results], [recompute_mod.UnitStatus.DONE])
        (new,) = done.results[0].operations
        self.assertEqual(self.query("SELECT op_type, status, revision_uid, supersedes_uid FROM "
                                    "gb_operation WHERE uid = ?", new),
                         [(design_provenance.STEPPED, "done", self.made["r2"],
                           design.handle.uid)])
        self.made["recomputed"] = new
        after = self.hashes()
        changed = sorted(name for name in after if after[name] != before.get(name))
        self.assertTrue(changed)
        self.assertTrue(all("bancos_del_hueco" in name for name in changed), changed)
        self.assertEqual(after["des_env_hueco"], before["des_env_hueco"])
        self.assertNotEqual(after["des_srf_bancos_del_hueco"], before["des_srf_bancos_del_hueco"])
        rows = self.berm_rows("Bancos del hueco")
        self.assertTrue(rows)
        for _sector, _profile, level, *_rest in rows:
            self.assertAlmostEqual((level - NEW_ANCHOR_M) / PROFILE_HEIGHT,
                                   round((level - NEW_ANCHOR_M) / PROFILE_HEIGHT), delta=1e-9)
        self.assertNotIn("des.magnitude_no_reference", self.report_codes("Bancos del hueco"),
                         "se comparó con el escalonado de V01.r1")
        old_figures = self.made["figures"]["pit_design"]
        figures = self.figures_of(new)
        self.assertNotEqual(figures["des.cut_m3"], old_figures["des.cut_m3"])
        self.assertEqual(design_provenance.settings_previous(self.settings_of(new)), {
            "operation": "Bancos del hueco", "revision": "V01.r1",
            "cut_m3": old_figures["des.cut_m3"], "fill_m3": old_figures["des.fill_m3"]})
        self.assertEqual(self.frozen(self.made["r1"]), frozen, "lo congelado no cambia")
        findings = graph.drain(versions_check.check_steps(self.project, [self.made["r1"]],
                                                          full=True))
        self.assertEqual([item.altered for item in findings], [False])

    def test_h_reproducing_v01_r1_gives_the_same_bit_for_bit(self) -> None:
        """CE-013-08, RF-013-31, RF-009-11: reproducir V01.r1, con otra ancla viva, da sin escribir
        nada en el proyecto las mismas salidas con el mismo hash (la envolvente y el escalonado del
        hueco, la envolvente del límite legal, la montera y su relleno) y las mismas cifras que
        lo congelado."""
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = last(reproduce_mod.reproduce_steps(self.project, self.made["r1"])).result
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before, "reproducir no escribe")
        self.assertEqual(report.not_reproducible, ())
        groups = ((("pit", "pit_design"), ["berm_table", "berms", "design_surface", "envelope",
                                           "report"]),
                  (("bowl",), ["envelope"]),
                  (("mound", "mound_design"), ["berm_table", "berms", "design_surface",
                                               "envelope", "report"]))
        for names, roles in groups:
            uids = [self.made[name].handle.uid for name in names]
            mine = [check for check in report.outputs if check.operation_uid in uids]
            with self.subTest(operations=names):
                self.assertEqual(sorted(check.role for check in mine), roles)
                self.assertTrue(all(check.same for check in mine), mine)
                self.assertTrue(all(check.reproduced_sha256 == check.frozen_sha256
                                    for check in mine))
            for name in names:
                reproduced = {check.key: check.reproduced for check in report.figures
                              if check.operation_uid == self.made[name].handle.uid}
                self.assertEqual(reproduced, self.made["figures"][name], name)
        self.assertTrue(report.matches)

    def test_i_reproducing_a_later_revision_repeats_what_it_was_compared_with(self) -> None:
        """CE-013-08, RF-013-30, RF-013-31, D-25 (RF-009-11): congelar V01 otra vez (V01.r2, con el
        escalonado recalculado, que se comparó con el de V01.r1) y reproducirla da las mismas
        salidas con el mismo hash y las mismas cifras que lo congelado, también su informe con
        el aviso de magnitud frente a la revisión de entonces, sin tenerla a mano."""
        self.clock.advance(minutes=1)
        outcome = last(freeze.freeze_steps(self.project, self.v1.uid,
                                           reason="Segunda entrega")).result
        self.made["r3"] = str(outcome.opened.uid)
        report = last(reproduce_mod.reproduce_steps(self.project, str(outcome.frozen.uid))).result
        self.assertEqual(report.not_reproducible, ())
        new = self.made["recomputed"]
        mine = [check for check in report.outputs if check.operation_uid == new]
        self.assertEqual(sorted(check.role for check in mine),
                         ["berm_table", "berms", "design_surface", "report"])
        self.assertTrue(all(check.same for check in report.outputs), report.outputs)
        reproduced = {check.key: check.reproduced for check in report.figures
                      if check.operation_uid == new}
        self.assertEqual(reproduced, self.figures_of(new))
        self.assertTrue(report.matches)

    # --- La verificación de la 012 --------------------------------------------------------------

    def verify(self, version: Any, name: str, finals: tuple[str, ...]) -> Any:
        """«Verificar un diseño por recinto…» (012) de las superficies ``finals`` frente a la de
        partida; el resultado (``VerifyResult``)."""
        self.clock.advance(minutes=1)
        stored = last(cstore.verify_project_steps(
            self.project, version=version.uid, name=name,
            start=surfaces.SurfaceRef(dataset=SURFACE, label="Partida"),
            finals=tuple(surfaces.SurfaceRef(dataset=final, label=final) for final in finals),
            budget_s=0.05)).result
        return stored.result

    def test_j_the_design_surfaces_verify_zero_cubic_metres_in_every_zone(self) -> None:
        """CE-013-06, RF-013-29, RF-012-21 (E4): «Verificar un diseño por recinto…» de las
        superficies de diseño de V01 (el hueco, ya recalculado, y el relleno de la montera) y de
        V02 (el frente tendido) da 0 m³ en todos los recintos que lo juzgan; mover una sola celda
        de la torre 1 m, en una copia de la del hueco, hace que falle ese recinto y solo él."""
        for version, names in ((self.v1, ("Bancos del hueco", "Terraplen de la montera")),
                               (self.v2, ("Frente tendido en bancos",))):
            finals = tuple(design_provenance.dataset_name("srf", name) for name in names)
            result = self.verify(version, f"Revisión {version.code}", finals)
            self.assertEqual(result.fails, (False,) * len(finals))
            for check in result.finals:
                judged = [total for total in check.totals
                          if total.counts in (compliance.Counts.CUT, compliance.Counts.FILL,
                                              compliance.Counts.ANY)]
                self.assertTrue(judged)
                for total in judged:
                    self.assertEqual(total.counted_m3, 0.0, total.code)
                    self.assertEqual(total.verdict, compliance.Verdict.COMPLIES, total.code)
                self.assertGreater(sum(total.cut_m3 + total.fill_m3 for total in check.totals),
                                   10_000.0, "la prueba mueve tierra de verdad")
        design = self.grid_of("srf", "Bancos del hueco").copy()
        tower = np.argwhere(self.masks1.zone("torre").mask(design.shape))
        row, col = (int(value) for value in tower[len(tower) // 2])
        design[row, col] -= 1.0
        self.write_surfaces(("tocada", raster_mod.Raster(
            cfx.site_start().grid, design, cfx.site_start().crs, cfx.site_start().vertical)))
        result = self.verify(self.v1, "Revisión con una celda movida", ("gis_dtm_tocada",))
        (check,) = result.finals
        self.assertEqual([total.code for total in check.totals
                          if total.verdict == compliance.Verdict.FAILS], ["torre"])
        self.assertEqual(check.zone("torre").counted_m3, self.area)

    # --- Un sector sin búsqueda y una restricción que cambia -----------------------------------

    def test_k_a_sector_without_a_search_is_shown_and_the_calculation_refuses(self) -> None:
        """RF-013-05, RF-013-06, CE-013-06, E5: con la búsqueda de intocables del sector 2 sin
        hacer, la vista previa lo marca (pendiente, y su aviso nombra el sector) y el cálculo se
        niega con ``des.sector_pending`` al avanzar, nombrando el sector y sin dejar nada (ni
        operación, ni dato, ni temporal); el sector 1 sigue sin pendiente. Sobre una copia propia
        del proyecto."""
        with dfx.open_design_project("gb-h1-p-") as (project, _clock):
            root = Path(project.root)
            with project.write_transaction() as conn:
                conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_2'")
            request = self.pit_request("Hueco sin busqueda")
            summary = last(steps.preview_steps(project, request, self.v1.uid)).result
            self.assertEqual([(s.code, s.touched, s.pending) for s in summary.sectors],
                             [("sector_1", True, False), ("sector_2", True, True)])
            (warning,) = summary.warnings("es")
            self.assertIn("Sector 2", warning)
            before = des_state(project, root)
            with self.assertRaises(messages.DesignError) as caught:
                last(steps.envelope_run(project, request, version=self.v1.uid))
            self.assertEqual(caught.exception.code, "des.sector_pending")
            self.assertIn("Sector 2", str(caught.exception))
            self.assertNotIn("Sector 1", str(caught.exception))
            self.assertEqual(des_state(project, root), before)
            only_one = dataclasses.replace(
                request, domain=design_model.WorkDomain(sectors=("sector_1",)))
            calculation = last(steps.envelope_run(project, only_one, version=self.v1.uid)).result
            calculation.discard()  # acotado al sector 1, que sí tiene su búsqueda, se calcula

    def test_l_changing_a_restriction_leaves_the_results_stale_with_their_cause(self) -> None:
        """CE-013-06, RF-013-04, RF-013-17 (E6): al cambiar una restricción (la 012), las máscaras
        quedan obsoletas y también, con su causa, las operaciones que las usaron y las
        superficies que escribieron, en las dos versiones; los datos congelados no cambian."""
        names = ("Bancos del hueco", "Terraplen de la montera")
        v1_ops = [self.made[key].handle.uid for key in ("pit", "bowl", "mound", "mound_design")]
        v1_ops.append(self.made["recomputed"])
        v2_ops = [self.made["front"].handle.uid, self.made["front_design"].handle.uid]
        with self.project.read() as conn:
            for uid in v1_ops + v2_ops:
                self.assertEqual(stale.item_causes(conn, "operation", uid), frozenset(), uid)
        rows = self.stored_constraints()
        frozen = self.frozen(self.made["r1"])
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [dataclasses.replace(rows[0], name=rows[0].name
                                                               + " (editada)")])
        for version in (self.v1, self.v2):
            self.assertIs(access.mask_state(self.project, version.uid)[0], access.MaskState.STALE)
        with self.project.read() as conn:
            for uid in v1_ops + v2_ops:
                causes = stale.item_causes(conn, "operation", uid)
                self.assertTrue(causes, uid)
            record = self.record(design_provenance.dataset_name("srf", names[0]), self.v1)
            self.assertTrue(stale.item_causes(conn, "dataset", record.uid))
        self.assertEqual(self.frozen(self.made["r1"]), frozen, "lo congelado no cambia")
        with self.assertRaises(access.MaskError):  # unas máscaras obsoletas no se usan
            access.load_masks(self.project, self.v1.uid)
