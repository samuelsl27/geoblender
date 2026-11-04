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
from tests.support import design_oracles as oracles
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


class RegularizationLoweredTest(unittest.TestCase):
    """RF-013-22, RF-013-26, RF-013-30 (spec 0.4; F-1): la regularización entre sectores baja una
    envolvente más empinada que el talud general de los sectores, y el cálculo lo avisa.

    Un frente de 16 × 32 celdas de 1 m con dos sectores de 16 columnas: el A con ``REST_5_35_6``
    (talud general 5 / (5/tan 35° + 6) = 20,83°) y el B con el mismo perfil y 12° impuestos. Las
    semillas, a 100 m, ocupan todo el sector A; la superficie de partida está a 160 m. La envolvente
    es de pendiente constante (la de la barrida) y la regularización usa la tangente más empinada de
    los sectores implicados (la del A). El recuento y el descenso máximo esperados salen del oráculo
    (Dijkstra sobre los 16 desplazamientos del *chamfer*), no de ``benching``."""

    SHAPE = (16, 32)
    SEED_M = 100.0
    START_M = 160.0
    IMPOSED_DEG = 12.0
    TOLERANCE_M = 1e-9
    SLOPES = (15.0, 20.8, 25.0, 35.0, 45.0, 60.0)

    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry = dfx.grid_from(*cls.SHAPE, 1.0)
        cls.labels = np.zeros(cls.SHAPE, dtype=np.int16)
        cls.labels[:, :16] = 1
        cls.labels[:, 16:] = 2
        cls.profiles = pipeline.bench_profiles(VALUES, [REST])
        cls.sectors = (SECTOR_A, SECTOR_B)
        cls.general_tan = 5.0 / (5.0 / math.tan(math.radians(35.0)) + 6.0)
        cls.berm_b = max(6.0, 5.0 / math.tan(math.radians(cls.IMPOSED_DEG))
                         - 5.0 / math.tan(math.radians(35.0)))

    def envelope(self, direction: str, metric: str, degrees: float) -> np.ndarray:
        """La envolvente de pendiente constante desde las semillas del sector A."""
        seed = np.full(self.SHAPE, np.nan)
        seed[:, :16] = self.SEED_M
        function = envelopes.chamfer_steps if metric == "chamfer5" else envelopes.exact_steps
        steps = function(seed, self.geometry, envelopes.constant_slope(degrees), direction,
                         name="e1")
        return list(steps)[-1].result.grid

    def job(self, envelope: np.ndarray, *, imposed: bool = True) -> Any:
        everything = np.ones(self.SHAPE, dtype=bool)
        masks = types.SimpleNamespace(cut_allowed=lambda: everything.copy(),
                                      fill_allowed=lambda: everything.copy(),
                                      fill_strip=lambda: np.zeros(self.SHAPE, dtype=bool))
        return pipeline.DesignJob(
            request=model.DesignRequest("Bancos", "Hoyo", "cut", REST), geometry=self.geometry,
            start=np.full(self.SHAPE, self.START_M), envelope=envelope, masks=masks,
            sectors=self.sectors, labels=self.labels,
            imposed={"b": self.IMPOSED_DEG} if imposed else {}, profiles=self.profiles,
            anchors=None, min_thickness_m=0.02, face_tolerance_deg=1.0, warning_ratio=2.0)

    @staticmethod
    def outcome(job: Any) -> Any:
        return list(pipeline.design_compute_steps(job))[-1].result

    def expected(self, envelope: np.ndarray) -> tuple[int, float, str]:
        """Lo que baja la regularización según el oráculo: las celdas, el descenso máximo (m) y los
        sectores donde baja."""
        regular = oracles.dijkstra(envelope, self.general_tan, 1.0, direction="up")
        lowered = regular < envelope - self.TOLERANCE_M
        names = [sector.name for index, sector in enumerate(self.sectors, start=1)
                 if bool((lowered & (self.labels == index)).any())]
        drop = float((envelope - regular)[lowered].max()) if lowered.any() else 0.0
        return int(lowered.sum()), drop, ", ".join(names)

    @staticmethod
    def notices(found: Any) -> list[Any]:
        return [n for n in found.report.notices if n.code == "des.regularization_lowered"]

    def test_a_steeper_envelope_than_the_sectors_warns_with_the_count_and_the_maximum(self) -> None:
        """RF-013-26, RF-013-30: una envolvente descendente *chamfer* de 45° es más empinada que el
        talud general del sector A (20,83°): la regularización la baja, el escalonado en corte
        queda por debajo de ``mín(envolvente, partida)`` en esas celdas (el efecto que se avisa) y
        el informe lleva **un** aviso con el recuento y el descenso máximo del oráculo, el talud con
        que se regularizó y los sectores donde bajó."""
        envelope = self.envelope("down", "chamfer5", 45.0)
        found = self.outcome(self.job(envelope))
        cells, drop, sectors = self.expected(envelope)
        self.assertGreater(cells, 100)
        self.assertGreater(drop, 5.0)
        below = np.minimum(envelope, self.START_M) - found.design
        self.assertGreater(float(below.max()), 1.0, "queda por debajo de la envolvente: se avisa")
        (notice,) = self.notices(found)
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(notice.values["cells"], cells)
        self.assertAlmostEqual(notice.values["drop"], drop, delta=self.TOLERANCE_M)
        self.assertAlmostEqual(notice.values["slope"], math.degrees(math.atan(self.general_tan)),
                               delta=1e-9)
        self.assertEqual(notice.values["sectors"], sectors)
        self.assertEqual(sectors, "Sector A, Sector B")
        self.assertIn(notice.text("es"), found.report.warnings("es"))
        self.assertIn(notice.text("en"), found.report.warnings("en"))

    def test_the_sweep_of_slopes_directions_and_metrics(self) -> None:
        """RF-013-26, RF-013-30: con 15, 20,8, 25, 35, 45 y 60°, las dos direcciones y las dos
        métricas, cada caso con celdas bajadas por la regularización lleva su aviso con el recuento
        y el máximo del oráculo (a ≤ 10⁻⁹ m), y los demás, ninguno; con 15° no baja nada, con 25° o
        más baja siempre, y con la exacta a 20,8° baja un poco (la regularización usa el *chamfer*
        escalado: 0,565 m en el H1) y con el *chamfer* no."""
        warned: dict[tuple[str, str, float], int] = {}
        for direction in ("down", "up"):
            for metric in ("chamfer5", "exact"):
                for degrees in self.SLOPES:
                    case = (direction, metric, degrees)
                    with self.subTest(case=case):
                        envelope = self.envelope(direction, metric, degrees)
                        found = self.outcome(self.job(envelope))
                        cells, drop, sectors = self.expected(envelope)
                        notices = self.notices(found)
                        warned[case] = len(notices)
                        if cells == 0:
                            self.assertEqual(notices, [])
                            continue
                        (notice,) = notices
                        self.assertEqual(notice.values["cells"], cells)
                        self.assertAlmostEqual(notice.values["drop"], drop, delta=self.TOLERANCE_M)
                        self.assertEqual(notice.values["sectors"], sectors)
        self.assertEqual(len(warned), 24)
        for direction in ("down", "up"):
            for metric in ("chamfer5", "exact"):
                self.assertEqual(warned[(direction, metric, 15.0)], 0)
                for degrees in (25.0, 35.0, 45.0, 60.0):
                    self.assertEqual(warned[(direction, metric, degrees)], 1)
            self.assertEqual(warned[(direction, "chamfer5", 20.8)], 0)
        self.assertEqual(warned[("down", "exact", 20.8)], 1)

    def test_without_an_imposed_slope_nothing_is_regularized_and_nothing_is_warned(self) -> None:
        """RF-013-26, RF-013-30: sin talud impuesto los dos sectores tienen el mismo talud general
        (el del perfil), no hay frontera que regularizar: ni celdas bajadas ni aviso, aunque la
        envolvente sea de 60°."""
        for direction in ("down", "up"):
            with self.subTest(direction=direction):
                envelope = self.envelope(direction, "chamfer5", 60.0)
                found = self.outcome(self.job(envelope, imposed=False))
                self.assertEqual(self.notices(found), [])

    def test_an_envelope_by_sectors_is_already_regular_and_is_not_warned(self) -> None:
        """RF-013-26, RF-013-30: con la envolvente de la pendiente de cada sector (entrar en una
        celda cuesta con la pendiente de la celda de llegada) la regularización no baja nada: 0
        celdas y ningún aviso, en las dos direcciones."""
        rules = [envelopes.SlopeRule(self.general_tan, 1.0),
                 envelopes.SlopeRule.from_degrees(self.IMPOSED_DEG, 1.0)]
        slope = envelopes.sector_slope(self.labels, rules)
        seed = np.full(self.SHAPE, np.nan)
        seed[:, :16] = self.SEED_M
        for direction in ("down", "up"):
            with self.subTest(direction=direction):
                envelope = list(envelopes.chamfer_steps(seed, self.geometry, slope, direction,
                                                        name="e1"))[-1].result.grid
                found = self.outcome(self.job(envelope))
                self.assertEqual(self.expected(envelope)[0], 0)
                self.assertEqual(self.notices(found), [])

    def test_the_design_still_follows_the_regularized_envelope(self) -> None:
        """RF-013-22, RF-013-26 (decisión de Samuel, 04/11/2026: avisar, no cambiar): el aviso no
        cambia el escalonado: la superficie de diseño es, a ≤ 10⁻⁹ m, la que sale de escalonar la
        envolvente regularizada del oráculo (cara primero, con la berma del talud impuesto en el
        sector B), recortarla con el *chamfer* de la cara y componerla con la de partida."""
        envelope = self.envelope("down", "chamfer5", 45.0)
        found = self.outcome(self.job(envelope))
        regular = oracles.dijkstra(envelope, self.general_tan, 1.0, direction="up")
        tan_face = math.tan(math.radians(35.0))
        berm = np.where(self.labels == 2, self.berm_b, 6.0)
        stairs = oracles.hand_stairs(regular, 5.0, tan_face, berm, 125.0)
        trimmed = np.maximum(oracles.dijkstra(stairs, tan_face, 1.0, direction="up"), regular)
        expected = np.minimum(self.START_M, trimmed)
        self.assertLessEqual(float(np.abs(found.design - expected).max()), 1e-9)
        self.assertEqual(len(self.notices(found)), 1)

    def test_the_figures_of_the_report_do_not_depend_on_the_notice(self) -> None:
        """RF-013-30: el aviso es solo un aviso: las cifras del informe son finitas y las mismas
        figuras (``des.*``) que sin él; el cálculo no modifica la envolvente, las etiquetas ni la
        superficie de partida."""
        envelope = self.envelope("down", "chamfer5", 45.0)
        job = self.job(envelope)
        before = (np.array(job.envelope, copy=True), np.array(job.labels, copy=True),
                  np.array(job.start, copy=True))
        found = self.outcome(job)
        for array, copy in zip((job.envelope, job.labels, job.start), before, strict=True):
            self.assertTrue(np.array_equal(array, copy, equal_nan=True))
        calm = self.outcome(self.job(self.envelope("down", "chamfer5", 15.0)))
        self.assertEqual([figure.key for figure in found.figures],
                         [figure.key for figure in calm.figures])
        self.assertTrue(all(math.isfinite(figure.value) for figure in found.figures))


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
