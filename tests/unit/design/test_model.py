# SPDX-License-Identifier: GPL-3.0-or-later
"""El modelo de las envolventes y el escalonado (spec 013, T02; plan 013 §5.3.1; RF-013-11 a
RF-013-13, RF-013-18, RF-013-21).

``design.model`` define las opciones y las peticiones del dominio, todas inmutables y sin cifras
mineras por defecto (D-7): la dirección de una envolvente (``DOWN``: ``E↓ = máx_q [s − d·t]``;
``UP``: ``E↑ = mín_q [s + d·t]``), su métrica (solo ``chamfer5`` y ``exact``: nunca el 3×3,
ADR-0014), el modo de pendiente (constante o por sectores), el sentido del escalonado, de dónde
salen las semillas, cómo se acota el dominio de trabajo y las peticiones de una envolvente y de
un escalonado. Las comprobaciones de fondo (pendiente fuera de rango, exacta con sectores, dominio
vacío…) son de las tareas que calculan; aquí solo los tipos.
"""

from __future__ import annotations

import dataclasses
import unittest

from tests.support.package import import_geoblender

model = import_geoblender("design.model")


def seeds() -> object:
    return model.SeedSource(model.SeedKind.SURFACE, surface="gis_dtm_partida",
                            zone=model.Zone(model.ZoneKind.DOMAIN))


class OptionsTest(unittest.TestCase):
    def test_direction_and_metric_are_the_only_ones(self) -> None:
        """RF-013-11, RF-013-12 (ADR-0014): dos direcciones y dos métricas, con su texto estable
        (el que se registra en la operación); no hay *chamfer* 3×3."""
        self.assertEqual([item.value for item in model.Direction], ["down", "up"])
        self.assertEqual([item.value for item in model.Metric], ["chamfer5", "exact"])
        self.assertEqual([item.value for item in model.SlopeMode], ["constant", "sectors"])
        self.assertEqual([item.value for item in model.BenchSense], ["cut", "fill"])
        self.assertEqual(model.Direction("down"), model.Direction.DOWN)
        for wrong in ("chamfer3", "chamfer", "3x3", ""):
            with self.subTest(metric=wrong), self.assertRaises(ValueError):
                model.Metric(wrong)

    def test_perimeter_segment(self) -> None:
        """RF-013-05, RF-013-09 (ADR-0029, D-23): el perímetro de actuación como sector único
        es el segmento ``perimeter__`` de la clave de un parámetro por sector."""
        self.assertEqual(model.PERIMETER_SEGMENT, "perimeter__")


class SeedSourceTest(unittest.TestCase):
    def test_the_three_origins_of_the_seeds(self) -> None:
        """RF-013-01: las semillas salen de las celdas de una superficie dentro de una zona
        (de una restricción, el dominio por defecto, un sector o una capa), de una cota fija en
        esas celdas o de una rejilla de cotas de la versión; cada una con lo suyo."""
        by_surface = model.SeedSource(
            model.SeedKind.SURFACE, surface="gis_dtm_partida",
            zone=model.Zone(model.ZoneKind.CONSTRAINT, "cantera_norte"))
        fixed = model.SeedSource(model.SeedKind.FIXED, elevation_m=182.5,
                                 zone=model.Zone(model.ZoneKind.LAYER, "recinto"))
        grid = model.SeedSource(model.SeedKind.GRID, grid="des_semillas")
        self.assertEqual((by_surface.kind, by_surface.zone.kind, by_surface.zone.name),
                         ("surface", "constraint", "cantera_norte"))
        self.assertEqual((fixed.elevation_m, fixed.zone.name), (182.5, "recinto"))
        self.assertEqual(grid.grid, "des_semillas")
        self.assertEqual([item.value for item in model.ZoneKind],
                         ["domain", "constraint", "sector", "layer"])
        self.assertEqual([item.value for item in model.SeedKind], ["surface", "fixed", "grid"])
        self.assertIsNone(model.Zone(model.ZoneKind.DOMAIN).name)

    def test_immutable_and_comparable(self) -> None:
        """Las peticiones se registran en la operación y se comparan: son inmutables, con
        igualdad por valor y se pueden usar como clave."""
        one, other = seeds(), seeds()
        self.assertEqual(one, other)
        self.assertEqual(hash(one), hash(other))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            one.surface = "otra"
        self.assertEqual(model.Zone("sector", "sector_2").kind, model.ZoneKind.SECTOR)


class WorkDomainTest(unittest.TestCase):
    def test_whole_domain_or_bounded_to_sectors_or_a_layer(self) -> None:
        """RF-013-02: el dominio de trabajo es el de las máscaras de la versión y se puede
        acotar a unos sectores o a una capa de polígonos del proyecto; sin acotar, es el entero
        (``bounded`` falso)."""
        whole = model.WorkDomain()
        self.assertFalse(whole.bounded)
        self.assertEqual((whole.sectors, whole.layer), ((), None))
        by_sectors = model.WorkDomain(sectors=["sector_2", "sector_1"])
        self.assertEqual(by_sectors.sectors, ("sector_2", "sector_1"))
        self.assertTrue(by_sectors.bounded)
        by_layer = model.WorkDomain(layer="recinto")
        self.assertTrue(by_layer.bounded)
        self.assertEqual(model.WorkDomain(sectors=("a",)), model.WorkDomain(sectors=["a"]))
        with self.assertRaises(TypeError):
            model.WorkDomain(sectors="sector_2")


class RequestsTest(unittest.TestCase):
    def test_envelope_request_defaults(self) -> None:
        """RF-013-11 a RF-013-14, RF-013-17: una petición de envolvente lleva su nombre, la
        dirección, las semillas, el modo de pendiente (con su valor si es constante), el factor
        de malla (1 por defecto), el alcance (ninguno por defecto), la métrica (*chamfer* 5×5 por
        defecto) y el acotado del dominio; los textos se vuelven sus enumerados."""
        request = model.EnvelopeRequest(
            name="Hueco inicial", direction="down", seeds=seeds(), slope_mode="constant",
            slope_deg=35.0)
        self.assertEqual(request.direction, model.Direction.DOWN)
        self.assertEqual(request.metric, model.Metric.CHAMFER5)
        self.assertEqual(request.slope_mode, model.SlopeMode.CONSTANT)
        self.assertEqual((request.slope_deg, request.mesh_factor, request.reach_m),
                         (35.0, 1.0, None))
        self.assertEqual(request.domain, model.WorkDomain())
        by_sectors = model.EnvelopeRequest(
            name="Por sectores", direction=model.Direction.UP, seeds=seeds(),
            slope_mode=model.SlopeMode.SECTORS, metric="chamfer5", reach_m=250.0)
        self.assertIsNone(by_sectors.slope_deg)
        self.assertEqual(by_sectors.reach_m, 250.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.name = "Otro"
        with self.assertRaises(ValueError):
            model.EnvelopeRequest(name="X", direction="sideways", seeds=seeds())
        with self.assertRaises(ValueError):
            model.EnvelopeRequest(name="X", direction="up", seeds=seeds(), metric="chamfer3")

    def test_design_request(self) -> None:
        """RF-013-21, RF-013-22 a RF-013-24: una petición de escalonado lleva la envolvente que
        se escalona, el sentido (corte o relleno), el perfil base, un perfil por sector (opcional)
        y la rejilla de anclas (ninguna: el ancla del perfil); los sectores salen ordenados por
        su código y los textos se vuelven sus enumerados."""
        request = model.DesignRequest(
            name="Diseño V01", envelope="Hueco inicial", sense="cut", base_profile="expl_10_60_6",
            sector_profiles={"sector_2": "rest_5_35_6", "sector_1": "desd_10_45_6"})
        self.assertEqual(request.sense, model.BenchSense.CUT)
        self.assertEqual(request.sector_profiles,
                         (("sector_1", "desd_10_45_6"), ("sector_2", "rest_5_35_6")))
        self.assertIsNone(request.anchor_grid)
        self.assertEqual(model.DesignRequest(name="Sin sectores", envelope="E", sense="fill",
                                             base_profile="rest_5_35_6").sector_profiles, ())
        self.assertEqual(hash(request), hash(dataclasses.replace(request)))
        with self.assertRaises(ValueError):
            model.DesignRequest(name="X", envelope="E", sense="dig", base_profile="p")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.envelope = "Otra"


if __name__ == "__main__":
    unittest.main()
