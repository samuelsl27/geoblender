# SPDX-License-Identifier: GPL-3.0-or-later
"""El cálculo completo de una envolvente y de un escalonado sobre entradas ya leídas (spec 013,
T15; RF-013-05, RF-013-06, RF-013-13, RF-013-19, RF-013-21, RF-013-24, RF-013-25, RF-013-29,
RF-013-30; plan 013 §5.3.2).

Aquí no hay proyecto: el cálculo recibe los parámetros como un diccionario clave → valor (lo que
anotó la operación o lo que congeló) y las superficies como arrays, y es el mismo cuando se
recalcula lo obsoleto y cuando se reproduce lo congelado. El relato de punta a punta, con el
proyecto, está en ``test_store.py`` (``VersionsStoryTest``).
"""

from __future__ import annotations

import math
import types
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

pipeline = import_geoblender("design.pipeline")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
envelopes = import_geoblender("design.envelopes")
seeds_mod = import_geoblender("design.seeds")

EXPL = "expl_10_60_6"
REST = "rest_5_35_6"
SECTOR_A, SECTOR_B = seeds_mod.SectorRef("a", "Sector A"), seeds_mod.SectorRef("b", "Sector B")


def values_of(*profiles: tuple[str, float, float, float, float], **other: object
              ) -> dict[str, object]:
    """Los valores de los parámetros de unos perfiles (código, h, α, B, z₀) y los demás."""
    found: dict[str, object] = dict(other)
    for code, height, face, berm, anchor in profiles:
        for param, value in (("height_m", height), ("face_deg", face), ("berm_m", berm),
                             ("anchor_m", anchor), ("mesh_factor", 1.0)):
            found[params.bench_key(code, param)] = value
    return found


VALUES = values_of((EXPL, 10.0, 60.0, 6.0, 125.0), (REST, 5.0, 35.0, 6.0, 125.0))


def envelope_request(**changes: Any) -> Any:
    base: dict[str, Any] = {
        "name": "Hoyo", "direction": "up", "slope_mode": "sectors",
        "seeds": model.SeedSource("fixed", elevation_m=1.0, zone=model.Zone("domain")),
        "base_profile": EXPL, "sector_profiles": {"b": REST}}
    return model.EnvelopeRequest(**{**base, **changes})


class ParametersTest(unittest.TestCase):
    def test_the_profiles_are_built_from_the_values_with_their_code_as_name(self) -> None:
        """RF-013-18, RF-013-19: los perfiles salen de los cinco valores de cada uno; el nombre
        libre no cambia ningún cálculo, así que es el código; sin repetir."""
        found = pipeline.bench_profiles(VALUES, [EXPL, REST, EXPL])
        self.assertEqual(list(found), [EXPL, REST])
        self.assertEqual((found[EXPL].name, found[EXPL].height_m, found[EXPL].face_deg,
                          found[EXPL].berm_m, found[EXPL].anchor_m, found[EXPL].mesh_factor),
                         (EXPL, 10.0, 60.0, 6.0, 125.0, 1.0))

    def test_a_profile_without_a_value_or_out_of_range_is_refused_naming_it(self) -> None:
        """RF-013-19: un valor que falta o está fuera de rango es ``DesignError`` con el perfil y
        el campo, también al leer solo el talud (una envolvente no lee el ancla)."""
        short = {key: value for key, value in VALUES.items() if not key.endswith(".berm_m")
                 or EXPL not in key}
        with self.assertRaises(messages.DesignError) as caught:
            pipeline.bench_profiles(short, [EXPL])
        self.assertEqual(caught.exception.code, "des.profile_value_missing")
        self.assertIn(EXPL, str(caught.exception))
        with self.assertRaises(messages.DesignError):
            pipeline.profile_rule(short, EXPL)
        steep = {**VALUES, params.bench_key(REST, "face_deg"): 90.0}
        with self.assertRaises(messages.DesignError) as caught:
            pipeline.bench_profiles(steep, [REST])
        self.assertEqual(caught.exception.code, "des.profile_value_range")
        no_anchor = {key: value for key, value in VALUES.items() if not key.endswith("anchor_m")}
        self.assertEqual(pipeline.profile_rule(no_anchor, EXPL).tan,
                         pipeline.profile_rule(VALUES, EXPL).tan,
                         "el ancla no cambia la pendiente de la envolvente")

    def test_the_rule_of_an_envelope_is_the_general_slope_of_the_profile_exactly(self) -> None:
        """RF-013-13, RF-013-20: la regla es ``h / (h/tan α + B)`` con el factor de malla, con los
        mismos números que ``BenchProfile.general_tan`` (si no, la envolvente y la regularización
        del escalonado no casarían)."""
        for code in (EXPL, REST):
            profile = pipeline.bench_profiles(VALUES, [code])[code]
            rule = pipeline.profile_rule(VALUES, code)
            self.assertEqual((rule.tan, rule.mesh_factor), (profile.general_tan, 1.0))

    def test_the_imposed_slopes_are_read_by_sector_code(self) -> None:
        """RF-013-08, RF-013-09: del talud impuesto de cada sector (``des.sector.{s}.…``), el
        valor comprobado de los que lo tienen; el perímetro como sector único usa su segmento; una
        fila sin valor no impone nada y uno fuera de (0; 90) ° es ``des.sector_slope_range``."""
        values = {"des.sector.a.max_general_slope_deg": 18.0,
                  "des.sector.b.max_general_slope_deg": None,
                  "des.sector.perimeter__.max_general_slope_deg": 30.0}
        perimeter = seeds_mod.SectorRef("", "el perímetro de actuación")
        self.assertEqual(pipeline.imposed_from(values, [SECTOR_A, SECTOR_B]), {"a": 18.0})
        self.assertEqual(pipeline.imposed_from(values, [perimeter]), {"": 30.0})
        self.assertEqual(pipeline.imposed_from({}, [SECTOR_A]), {})
        with self.assertRaises(messages.DesignError) as caught:
            pipeline.imposed_from({"des.sector.a.max_general_slope_deg": 90.0}, [SECTOR_A])
        self.assertEqual(caught.exception.code, "des.sector_slope_range")

    def test_what_the_domain_touches_follows_the_order_of_the_sectors(self) -> None:
        """RF-013-06, D-15: los sectores con alguna celda en la máscara, en su orden."""
        labels = np.array([[0, 1, 1, 2], [0, 0, 2, 2]], dtype=np.int16)
        mask = np.ones(labels.shape, dtype=bool)
        self.assertEqual(pipeline.touched_in([SECTOR_A, SECTOR_B], labels, mask), ("a", "b"))
        mask[:, 2:] = False
        self.assertEqual(pipeline.touched_in([SECTOR_A, SECTOR_B], labels, mask), ("a",))
        self.assertEqual(pipeline.touched_in([SECTOR_A, SECTOR_B], labels, np.zeros_like(mask)), ())

    def test_what_a_design_was_compared_with_becomes_a_previous(self) -> None:
        """D-25: lo anterior de los ajustes es un ``Previous``; sin ello, ninguno."""
        self.assertIsNone(pipeline.previous_of(None))
        found = pipeline.previous_of({"operation": "Diseño", "revision": "V01.r1",
                                      "cut_m3": 1000.0, "fill_m3": 0.0})
        self.assertEqual((found.operation, found.revision, found.cut_m3, found.fill_m3),
                         ("Diseño", "V01.r1", 1000.0, 0.0))


class EnvelopeSlopeTest(unittest.TestCase):
    LABELS = np.array([[0, 1, 1, 2], [0, 1, 2, 2]], dtype=np.int16)

    def test_a_constant_slope_does_not_read_the_sectors(self) -> None:
        """RF-013-13: con la pendiente constante, la de la petición, sin leer sectores ni perfiles
        (no hace falta ningún valor)."""
        request = envelope_request(slope_mode="constant", slope_deg=35.0, base_profile=None,
                                   sector_profiles={})
        slope = pipeline.envelope_slope(request, [], np.zeros((2, 2), dtype=np.int16), {})
        self.assertTrue(slope.uniform)
        self.assertEqual(slope.max_tan, envelopes.constant_slope(35.0).max_tan)

    def test_each_sector_takes_its_imposed_slope_or_that_of_its_profile(self) -> None:
        """RF-013-13, RF-013-21: por sectores, el talud general máximo impuesto o, si no lo tiene,
        el del perfil asignado (el del sector o el base); las celdas sin sector, el del perfil base
        (CE-013-04, CE-013-05)."""
        values = {**VALUES, "des.sector.a.max_general_slope_deg": 18.0}
        slope = pipeline.envelope_slope(envelope_request(sector_profiles={"b": REST}),
                                        [SECTOR_A, SECTOR_B], self.LABELS, values)
        tan = np.asarray(slope.tan)
        self.assertEqual(tan.shape, self.LABELS.shape)
        base = pipeline.profile_rule(VALUES, EXPL).effective
        a = envelopes.SlopeRule.from_degrees(18.0, 1.0).effective
        b = pipeline.profile_rule(VALUES, REST).effective
        self.assertEqual(sorted({float(v) for v in tan[self.LABELS == 0]}), [base])
        self.assertEqual(sorted({float(v) for v in tan[self.LABELS == 1]}), [a])
        self.assertEqual(sorted({float(v) for v in tan[self.LABELS == 2]}), [b])
        base_only = pipeline.envelope_slope(envelope_request(sector_profiles={}),
                                            [SECTOR_A, SECTOR_B], self.LABELS, VALUES)
        self.assertEqual({float(v) for v in np.asarray(base_only.tan)[self.LABELS == 2]}, {base})

    def test_a_sector_without_a_slope_or_a_profile_is_refused_naming_it(self) -> None:
        """RF-013-13, RF-013-16: un sector sin talud impuesto y sin perfil (ni base) no tiene
        pendiente: ``des.profile_unassigned`` con el sector, antes de calcular nada."""
        request = envelope_request(base_profile=None, sector_profiles={"b": REST})
        with self.assertRaises(messages.DesignError) as caught:
            pipeline.envelope_slope(request, [SECTOR_A, SECTOR_B], self.LABELS, VALUES)
        self.assertEqual(caught.exception.code, "des.profile_unassigned")
        self.assertIn("Sector A", str(caught.exception))

    def test_a_profile_for_a_sector_that_does_not_exist_is_refused(self) -> None:
        """RF-013-21: asignar un perfil a un sector que no es de los del proyecto es
        ``des.sector_unknown`` con los que hay."""
        request = envelope_request(sector_profiles={"z": REST})
        with self.assertRaises(messages.DesignError) as caught:
            pipeline.envelope_slope(request, [SECTOR_A, SECTOR_B], self.LABELS, VALUES)
        self.assertEqual(caught.exception.code, "des.sector_unknown")
        self.assertIn("a, b", str(caught.exception))


class DesignComputeTest(unittest.TestCase):
    """RF-013-22 a RF-013-30: un escalonado pequeño, a mano, por el cálculo completo."""

    SHAPE = (40, 60)
    DEPTH_M = 5.0

    def job(self, **changes: Any) -> Any:
        grid = dfx.grid_from(*self.SHAPE, 1.0)
        start = np.full(self.SHAPE, 100.0)
        envelope = np.full(self.SHAPE, np.nan)
        envelope[10:30, 10:50] = 100.0 - self.DEPTH_M  # una cota sobre un banco: 95 = 125 − 3·10
        labels = np.zeros(self.SHAPE, dtype=np.int16)
        labels[:, 30:] = 1
        everything = np.ones(self.SHAPE, dtype=bool)
        masks = types.SimpleNamespace(cut_allowed=lambda: everything.copy(),
                                      fill_allowed=lambda: everything.copy(),
                                      fill_strip=lambda: np.zeros(self.SHAPE, dtype=bool))
        base: dict[str, Any] = {
            "request": model.DesignRequest("Bancos", "Hoyo", "cut", EXPL, {"b": REST}),
            "geometry": grid, "start": start, "envelope": envelope, "masks": masks,
            "sectors": (SECTOR_B,), "labels": labels, "imposed": {},
            "profiles": pipeline.bench_profiles(VALUES, [EXPL, REST]), "anchors": None,
            "min_thickness_m": 0.02, "face_tolerance_deg": 1.0, "warning_ratio": 2.0}
        return pipeline.DesignJob(**{**base, **changes})

    @staticmethod
    def outcome(job: Any) -> Any:
        found = None
        for found in pipeline.design_compute_steps(job):
            pass
        return found.result

    def test_a_cut_on_a_bench_level_moves_the_volume_by_hand(self) -> None:
        """RF-013-22, RF-013-29, RF-013-30: una envolvente plana a 95 m, sobre un banco del perfil
        (125 − 3·10), baja el terreno de 100 a 95 m en las celdas de la envolvente: 5 m en
        20 × 40 celdas de 1 m = 4.000 m³ de desmonte, ni un metro más, ni nada de relleno; la
        cota queda a 95 m (no la deja en otro banco) y el área sin sector es la de las celdas del
        dominio sin sector (los 20 × 20 m del oeste)."""
        found = self.outcome(self.job())
        design = found.design
        self.assertEqual(float(np.nanmin(design)), 95.0)
        self.assertTrue(np.all(design[10:30, 10:50] <= 100.0))
        self.assertEqual(found.report.cut_m3, 4000.0)
        self.assertEqual(found.report.moved_cells, 800)
        self.assertEqual(found.report.fill_m3, 0.0)
        self.assertEqual(found.unassigned_area_m2, 20 * 20 * 1.0)
        self.assertEqual([figure.key for figure in found.figures],
                         [key for key in (
                             "des.cut_m3", "des.fill_m3", "des.moved_area_m2",
                             "des.slope_p90_deg", "des.slope_p99_deg", "des.slope_max_deg",
                             "des.edge_step_max_m", "des.berm_count", "des.nodata_area_m2")])
        self.assertTrue(all(math.isfinite(figure.value) for figure in found.figures))
        self.assertIn("Bancos", found.message)

    def test_the_berms_are_attributed_to_the_sector_and_profile_of_their_cells(self) -> None:
        """RF-013-28, RF-013-21: la tabla de bermas nombra el sector y el perfil de cada zona: el
        base en las celdas sin sector (código vacío) y el de cada sector en las suyas."""
        found = self.outcome(self.job())
        scopes = {(row.sector, row.profile) for row in found.berms.table}
        self.assertEqual(scopes, {("", EXPL), ("b", REST)})
        for row in found.berms.table:
            self.assertEqual(row.level_m, 95.0)
            self.assertLess(abs(row.anchor_diff_m), 1e-6)

    def test_a_grid_of_anchors_replaces_the_anchor_of_the_profile(self) -> None:
        """RF-013-24, RF-013-22, RF-013-28: con una rejilla de anclas a 98 m, los bancos se anclan a
        98 + h·n, no a los 125 m del perfil. Sin sector (perfil de 10 m), la cota de la envolvente
        (95) cae en la berma de 98 m (excava de menos): 2 m en 400 celdas; en el sector b (perfil
        de 5 m, cara de 35°, berma de 6 m), sobre una cara, a 93 + 0,4·(5 + 6·tan 35°) m: el
        desmonte es la suma a mano, y solo la berma sin sector está en la tabla, a 98 m."""
        found = self.outcome(self.job(anchors=np.full(self.SHAPE, 98.0)))
        face = 93.0 + 0.4 * (5.0 + 6.0 * math.tan(math.radians(35.0)))
        self.assertAlmostEqual(found.report.cut_m3, 400 * 2.0 + 400 * (100.0 - face), places=6)
        self.assertEqual({(row.sector, row.level_m, row.anchor_m) for row in found.berms.table},
                         {("", 98.0, 98.0)})
        self.assertAlmostEqual(float(np.nanmin(found.design)), face, places=9)

    def test_the_envelope_is_regularized_between_sectors_with_other_slopes(self) -> None:
        """RF-013-26, RF-013-27: una pared de 10 m entre dos sectores con taludes distintos se
        regulariza: solo bajan las celdas del lado alto que están a menos de 10 m / tan α (la
        tangente más empinada de la frontera) de la pared, no todo el lado; la superficie de diseño
        sigue a la envolvente regularizada, que queda a 105 m lejos de la pared."""
        envelope = np.full(self.SHAPE, np.nan)
        envelope[10:30, 10:30] = 105.0
        envelope[10:30, 30:50] = 95.0
        found = self.outcome(self.job(start=np.full(self.SHAPE, 110.0), envelope=envelope))
        design = found.design
        self.assertEqual(float(design[20, 12]), 105.0, "lejos de la pared no cambia")
        self.assertLess(float(design[20, 29]), 105.0, "junto a la pared baja")
        self.assertGreater(float(design[20, 29]), 95.0)
        self.assertTrue(np.all(np.diff(design[20, 12:30]) <= 1e-9), "no sube hacia la pared")

    def test_the_imposed_slope_widens_the_berms_of_its_sector_only(self) -> None:
        """RF-013-25: el sector con talud impuesto de 18° tiene la berma ``máx(B, h/tan β − h/tan
        α)``, así que sus bancos se colocan de otra manera sobre una envolvente inclinada, y los
        del otro sector, con el perfil y el ancla de siempre, no cambian."""
        envelope = np.full(self.SHAPE, np.nan)
        columns = np.arange(self.SHAPE[1], dtype=np.float64)
        envelope[10:30, 10:50] = 90.0 + 0.1 * (columns[10:50] - 10.0)
        job = self.job(start=np.full(self.SHAPE, 150.0), envelope=envelope)
        plain = self.outcome(job).design
        imposed = self.outcome(self.job(start=np.full(self.SHAPE, 150.0), envelope=envelope,
                                        imposed={"b": 18.0})).design
        self.assertTrue(np.array_equal(plain[:, :30], imposed[:, :30], equal_nan=True))
        self.assertFalse(np.array_equal(plain[:, 30:], imposed[:, 30:], equal_nan=True))

    def test_the_mesh_factor_of_the_profile_trims_the_faces(self) -> None:
        """RF-013-27, RF-013-20: el factor de malla de cada perfil rebaja la cara que se permite
        al recortar (una malla de 0,5 deja la cara con la mitad de tangente): sobre una envolvente
        inclinada, la superficie de diseño cambia y solo en el sector de ese perfil."""
        envelope = np.full(self.SHAPE, np.nan)
        columns = np.arange(self.SHAPE[1], dtype=np.float64)
        envelope[10:30, 10:50] = 90.0 + 0.5 * (columns[10:50] - 10.0)
        start = np.full(self.SHAPE, 200.0)
        plain = self.outcome(self.job(start=start, envelope=envelope)).design
        meshed = {**VALUES, params.bench_key(REST, "mesh_factor"): 0.5}
        coarse = self.outcome(self.job(
            start=start, envelope=envelope,
            profiles=pipeline.bench_profiles(meshed, [EXPL, REST]))).design
        self.assertTrue(np.array_equal(plain[:, :30], coarse[:, :30], equal_nan=True))
        self.assertFalse(np.array_equal(plain[:, 30:], coarse[:, 30:], equal_nan=True))

    def test_the_face_of_the_report_is_that_of_the_profile_of_each_cell(self) -> None:
        """RF-013-30: el aviso de inclinación pasada de la cara compara cada celda con la cara de
        su perfil más la tolerancia: con una pared de 10 m en el sector de cara de 35°, el límite
        es 36° (35 + 1), no el 61° del perfil base."""
        envelope = np.full(self.SHAPE, np.nan)
        envelope[10:30, 30:50] = 90.0
        found = self.outcome(self.job(start=np.full(self.SHAPE, 100.0), envelope=envelope))
        warnings = [notice for notice in found.report.notices
                    if notice.code == "des.slope_over_face"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].values["limit"], 36.0)

    def test_the_sectors_with_a_pending_search_are_marked_in_the_report(self) -> None:
        """RF-013-06: los sectores pendientes que recibe el cálculo salen en el informe con su
        marca (un aviso por sector), y sin ellos, ninguna."""
        marks = lambda found: [notice.values["sector"] for notice in found.report.notices  # noqa: E731
                               if notice.code == "des.sector_pending_mark"]
        self.assertEqual(marks(self.outcome(self.job())), [])
        self.assertEqual(marks(self.outcome(self.job(pending=("Sector B",)))), ["Sector B"])

    def test_a_grid_of_anchors_without_elevation_in_the_domain_is_refused(self) -> None:
        """RF-013-24, RF-013-16: unos anclas sin cota en celdas del dominio no se rellenan ni se
        ignoran: ``des.anchor_nodata`` con el número de celdas, antes de escribir nada."""
        anchors = np.full(self.SHAPE, 102.0)
        anchors[12:14, 12:15] = np.nan
        with self.assertRaises(messages.DesignError) as caught:
            self.outcome(self.job(anchors=anchors, request=model.DesignRequest(
                "Bancos", "Hoyo", "cut", EXPL, anchor_grid="gis_dtm_anclas")))
        self.assertEqual(caught.exception.code, "des.anchor_nodata")
        self.assertEqual(caught.exception.values["cells"], 6)
        outside = np.full(self.SHAPE, 102.0)
        outside[0:3, 0:3] = np.nan  # fuera del dominio: no importa
        self.outcome(self.job(anchors=outside))

    def test_a_profile_for_a_sector_that_does_not_exist_is_refused(self) -> None:
        """RF-013-21: el escalonado se niega, como la envolvente, si asigna un perfil a un sector
        que no existe."""
        with self.assertRaises(messages.DesignError) as caught:
            self.outcome(self.job(request=model.DesignRequest("Bancos", "Hoyo", "cut", EXPL,
                                                               {"zzz": REST})))
        self.assertEqual(caught.exception.code, "des.sector_unknown")

    def test_nothing_is_modified(self) -> None:
        """Regla 6 de AGENTS.md: ni la superficie de partida ni la envolvente ni las etiquetas ni
        las anclas se modifican."""
        job = self.job(anchors=np.full(self.SHAPE, 102.0))
        before = [np.array(array, copy=True) for array in (job.start, job.envelope, job.labels,
                                                           job.anchors)]
        self.outcome(job)
        for array, copy in zip((job.start, job.envelope, job.labels, job.anchors), before,
                               strict=True):
            self.assertTrue(np.array_equal(array, copy, equal_nan=True))

    def test_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-013-33: cerrar el generador a mitad no deja nada (aquí no se escribe): se puede
        volver a empezar y da lo mismo."""
        job = self.job()
        steps = pipeline.design_compute_steps(job)
        next(steps)
        steps.close()
        again = self.outcome(job)
        self.assertEqual(float(np.nanmin(again.design)), 95.0)


class EnvelopeComputeTest(unittest.TestCase):
    def test_the_envelope_is_clipped_to_the_work_domain_and_measured(self) -> None:
        """RF-013-02, RF-013-17: la rejilla de la envolvente tiene ``NaN`` fuera del dominio de
        trabajo; las celdas, el área y las cotas mínima y máxima son las de lo que queda; sin
        superficie de partida no hay desmonte ni terraplén."""
        grid = dfx.grid_from(20, 30, 2.0)
        seed = np.full(grid.shape, np.inf)
        seed[10, 15] = 50.0
        mask = np.zeros(grid.shape, dtype=bool)
        mask[5:15, 5:25] = True
        domain = seeds_mod.domain_of(mask, np.zeros(grid.shape, dtype=np.int16), (), grid.cell_area)
        seeds = seeds_mod.collect_seeds(np.where(np.isfinite(seed), seed, np.nan), None, domain,
                                        grid)
        request = model.EnvelopeRequest(
            "Cono", "up", model.SeedSource("fixed", elevation_m=50.0, zone=model.Zone("domain")),
            slope_deg=45.0)
        job = pipeline.EnvelopeJob(request, seeds, pipeline.envelope_slope(
            request, (), np.zeros(grid.shape, dtype=np.int16), {}), None, 0.02)
        found = None
        for found in pipeline.envelope_compute_steps(job):
            pass
        outcome = found.result
        finite = np.isfinite(outcome.grid)
        self.assertTrue(np.array_equal(finite, mask))
        self.assertEqual(float(outcome.grid[10, 15]), 50.0)
        keys = {figure.key: figure.value for figure in outcome.figures}
        self.assertEqual(keys["des.env_cells"], float(mask.sum()))
        self.assertEqual(keys["des.env_area_m2"], float(mask.sum()) * 4.0)
        self.assertEqual((keys["des.env_min_m"], keys["des.env_max_m"]),
                         (50.0, float(np.nanmax(outcome.grid))))
        self.assertNotIn("des.env_cut_m3", keys)
        withstart = pipeline.EnvelopeJob(request, seeds, job.slope, np.full(grid.shape, 100.0),
                                         0.02)
        for found in pipeline.envelope_compute_steps(withstart):
            pass
        keys = {figure.key: figure.value for figure in found.result.figures}
        self.assertGreater(keys["des.env_cut_m3"], 0.0)
        self.assertEqual(keys["des.env_fill_m3"], 0.0)


if __name__ == "__main__":
    unittest.main()
