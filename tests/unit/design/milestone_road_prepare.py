# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la pista con lo que cambia el proyecto (spec 017, T19; HU-017-1 y HU-017-2; RF-017-02, RF-017-03, RF-017-04, RF-017-05, RF-017-06; RF-015-07; RF-009-21; D-3 y D-16; plan 017
§5.2.3, §5.4 A1 y §5.7 P-5), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas en ``test_road_prepare.py``.

- **Una versión que no se edita** (:class:`ClosedVersionTest`): sin versión activa o con V01 SUPERADA no se prepara.
- **Un sector sin búsqueda de intocables** (:class:`PendingSectorTest`, RF-015-07): borrada la búsqueda del «Sector oeste», una pista cuyo pasillo, o cuya sección, lo toca se rechaza
  con ``des.sector_pending`` y una que queda lejos de él (más allá de su semianchura y de su alcance) no; ``refuse_pending`` se llama aquí.
- **La cantera de la 014 de la versión** (:class:`QuarryStartTest`, RF-017-05, D-3): la partida por defecto es la superficie de explotación al día (una segunda cantera, obsoleta,
  no cuenta) y su conflicto con la entidad que ya parte de ella; sobre la **final restaurada** el aviso «no llega al fondo» con las dos cotas (a); y los **otros diseños** de la versión
  con los que se compara (b: T19-b).
- **Una plataforma de destino** (:class:`PlatformDestinationTest`, RF-017-03, RF-017-04, T19-c, RF-015-15): el destino ``entity:PLT-001`` es el punto de la capa que cae en su huella
  (ni ninguno ni varios), su cota es la de su ``des_psf_`` y la pista **se apoya en ella** (la superficie y la tabla de su huella son entradas; la fila ``supports`` lo dice).

Sobre el proyecto de las pistas (``tests.support.road_data``, rejilla de 2 m, 200 × 200 celdas). **Nada se escribe** al preparar; lo que cambia el proyecto es el montaje de cada clase.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import (
    GRID,
    KEY,
    PROFILE,
    RAMP,
    PrepareCase,
    absolute,
    drive,
    never,
    request,
)

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
gis = import_geoblender("gis")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
versions_model = import_geoblender("core.versions.model")

PROBE = "des.probe_road"
"""El tipo de operación de prueba de V01 que escribe las dos superficies de una cantera (solo desde esta prueba)."""
BUDGET_S = 3.0
"""Preparar una pista de la rejilla gruesa, con todo lo que lee del proyecto (RNF-017-06: cada unidad ≤ 0,2 s)."""
EAST_LAYER = "gis_fea_pistas_este"
EAST_POINTS = (("Este 1", (320.0, 100.0)), ("Este 2", (380.0, 100.0)), ("Cerca 1", (210.0, 100.0)), ("Cerca 2", (260.0, 100.0)))
"""Los puntos al este del «Sector oeste» (de x = 20 a 190 m): una pista entre los dos primeros queda lejos (no lo toca ni con su sección ni con el alcance de su borde) y una entre los
dos últimos tiene su pasillo a más de 16 m de él, pero el alcance de su borde (60 m) lo toca."""


class ClosedVersionTest(PrepareCase):
    """RF-009-21: una pista de una versión no se prepara si la versión no se edita (su propia copia del proyecto: la prueba cierra V01)."""

    def test_a_version_that_is_not_editable(self) -> None:
        """RF-009-21: sin versión activa (``core.version_required``) o con V01 SUPERADA (``core.version_not_editable``) no se prepara, sin escribir nada."""
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(request(), version=None)
        self.assertEqual(caught.exception.code, "core.version_required")
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v1.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?", ("Prueba de la 017", self.v1.uid))
        closed = self.state()
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(request())
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(self.state(), closed)


class PendingSectorTest(PrepareCase):
    """RF-015-07: un sector sin búsqueda de intocables vigente rechaza el cálculo solo si lo toca el pasillo de la ruta o la sección de la pista."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        x_y = [absolute(point) for _name, point in EAST_POINTS]
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(EAST_LAYER, "point", tuple(((np.array([[x, y]]),),) for x, y in x_y), tuple(name for name, _ in EAST_POINTS), {}))
        with cls.project.write_transaction() as conn:  # el «Sector oeste» (x de 20 a 190 m): sin búsqueda vigente
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_1'")
        cls.clock.advance(minutes=1)

    def test_the_corridor_in_a_pending_sector(self) -> None:
        """RF-015-07: la rampa (de x = 100 a 300 m) cruza el «Sector oeste»: se rechaza con ``des.sector_pending`` nombrando el sector y la orden que lo arregla, sin escribir nada."""
        error = self.refused(request(), "des.sector_pending")
        self.assertIn("Sector oeste", error.text)
        self.assertIn("Buscar elementos intocables por sector", error.text)
        self.assertEqual(error.values["codes"], "sector_1")

    def test_a_road_far_from_the_pending_sector(self) -> None:
        """RF-015-07: una pista al este (de x = 320 a 380 m, a más de 100 m del sector) no pide su búsqueda: se prepara; con un alcance de 400 m la sección **sí** lo toca y se rechaza."""
        east = request("Pista del este", layer=EAST_LAYER, origin="Este 1", destination="Este 2")
        before = self.state()
        prepared = self.prepare(east)
        self.assertEqual(self.state(), before)
        self.assertEqual(prepared.job.geometry.origin, absolute(EAST_POINTS[0][1]))
        self.refused(request("Pista del este", layer=EAST_LAYER, origin="Este 1", destination="Este 2", margin_m=400.0), "des.sector_pending")

    def test_the_reach_of_the_edge_touches_the_sector(self) -> None:
        """RF-015-07: una pista cuyo pasillo queda a más de 16 m del sector, pero cuyo borde llega a 60 m (el alcance del perfil), también lo toca: se rechaza; la lejana, no."""
        near = request("Pista cercana", layer=EAST_LAYER, origin="Cerca 1", destination="Cerca 2", margin_m=2.0)
        self.refused(near, "des.sector_pending")
        self.prepare(request("Pista lejana", layer=EAST_LAYER, origin="Este 1", destination="Este 2", margin_m=2.0))

    def test_a_line_mode_in_a_pending_sector(self) -> None:
        """RF-015-07: «sobre un eje» también: la línea del escalón (de x = 100 a 300 m) toca el «Sector oeste»."""
        self.refused(request(mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("escalon")), "des.sector_pending")


class QuarryStartCase(PrepareCase):
    """Lo de ``PrepareCase`` más las dos superficies de dos canteras de la 014 en V01 (cuatro datos que escribe una operación de prueba: ``des_exp_cantera`` y ``des_fin_cantera``, y los de
    ``Otra``, que se deja **obsoleta**)."""

    @classmethod
    def write_quarry(cls, name: str, *, shift: float = 0.0, supersedes: str | None = None) -> str:
        """Escribe en V01 las dos superficies de una cantera de nombre ``name`` (la de explotación, la cantera con bancos, y la final, 20 m más arriba) con una operación de prueba;
        ``supersedes`` es la operación de prueba anterior de la misma cantera, que la nueva sustituye (los mismos nombres, otro contenido: T22)."""
        begun = store._start(cls.project, PROBE, name, cls.v1, None, {"name": name}, (), (), supersedes)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, PROBE, name, version=cls.v1.uid, supersedes=supersedes) as writer:
            exploitation = rd.bank_surface(GRID) + shift
            drive(writer.grid_steps(provenance.EXPLOITATION_GRID, gis.Raster(GRID, exploitation, rd.CRS, rd.VERTICAL)))
            drive(writer.grid_steps(provenance.FINAL_GRID, gis.Raster(GRID, exploitation + 20.0, rd.CRS, rd.VERTICAL)))
            stored = writer.commit(begun, message="Superficies de la prueba de preparar la pista")
        cls.clock.advance(minutes=1)
        return str(stored.handle.uid)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        probe = provenance.OperationType(PROBE, "Surfaces of a quarry of the tests", (provenance.EXPLOITATION_GRID, provenance.FINAL_GRID), ())
        cls.enterClassContext(mock.patch.object(provenance, "OPERATION_TYPES_BY_NAME", MappingProxyType({**provenance.OPERATION_TYPES_BY_NAME, PROBE: probe})))
        cls.enterClassContext(registered(probe.definition(never)))
        cls.write_quarry("Cantera")
        cls.write_quarry("Otra", shift=1.0)
        with cls.project.read() as conn:
            uid = conn.execute("SELECT uid FROM gb_dataset WHERE name = 'des_exp_otra'").fetchone()[0]
        with cls.project.write_transaction() as conn:  # «Otra» está obsoleta: ni la toca la 008 aquí ni cuenta como partida por defecto
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, since) VALUES ('dataset', ?, 'dataset_changed', ?, '2026-11-21T00:00:00Z')", (uid, uid))


class QuarryStartTest(QuarryStartCase):
    """RF-017-05, D-3: la partida por defecto, el aviso de la final restaurada y los otros diseños de la versión."""

    def test_the_default_start_is_the_exploitation_surface_of_the_quarry(self) -> None:
        """RF-017-05, D-3: con una cantera al día (y otra obsoleta) la partida por defecto es su superficie de explotación, libre (ninguna entidad parte de ella); una pista sin partida
        parte de ella, con su dato como entrada de la operación."""
        found = road_store.default_start(self.project, self.v1)
        self.assertEqual((found.ref, found.kind, found.name, found.conflict), ("des_exp_cantera", "exploitation", "des_exp_cantera", None))
        asked = request("Pista de la cantera", layer=rd.ENTRIES_LAYER, origin="Entrada de la cantera de bancos", destination="Entrada del tajo", surface="")
        prepared = self.prepare(asked)
        self.assertEqual((prepared.start_surface, prepared.start_ref), ("des_exp_cantera", "des_exp_cantera"))
        self.assertIn(("des_exp_cantera", provenance.SURFACE_ROLE), [(use.item, str(use.role)) for use in prepared.start.inputs])
        self.assertEqual({row.param: row.value for row in prepared.rows}["start"], "des_exp_cantera")

    def test_a_road_on_the_restored_final_warns_that_it_does_not_reach_the_bottom(self) -> None:
        """RF-017-05 (a), T19-a: sobre la final restaurada (20 m más arriba que la explotación) la cota mínima alcanzable desde el origen, con la pendiente de diseño y la calzada del
        perfil, es 20 m mayor que sobre la de explotación: el aviso lo dice (y no impide prepararla); sobre la de explotación, ninguno."""
        asked = request("Pista de la final", layer=rd.ENTRIES_LAYER, origin="Entrada de la cantera de bancos", destination="Entrada del tajo", surface="des_fin_cantera")
        before = self.state()
        prepared = self.prepare(asked)
        self.assertEqual(self.state(), before)
        (notice,) = prepared.notices
        self.assertEqual(notice.code, "des.road_start_is_final")
        self.assertEqual((notice.values["entity"], notice.values["surface"]), ("Pista de la final", "des_fin_cantera"))
        self.assertAlmostEqual(notice.values["z_final"] - notice.values["z_pit"], 20.0, places=9)
        self.assertEqual(self.prepare(request("Pista de la cantera", layer=rd.ENTRIES_LAYER, origin="Entrada de la cantera de bancos", destination="Entrada del tajo",
                                              surface="des_exp_cantera")).notices, ())

    def test_the_other_designs_do_not_start_from_the_start_surface(self) -> None:
        """RF-017-05 (b), T19-b: los otros diseños de la versión con los que se compara la partida son las superficies de diseño que **no** parten de ella: de la explotación de la
        cantera, las de ``Otra`` (no la final de la misma cantera, que escribió la misma operación); de la de ``Otra``, las de la cantera."""
        self.assertEqual(road_store.other_designs(self.project, self.v1, "des_exp_cantera"), ("des_exp_otra", "des_fin_otra"))
        self.assertEqual(road_store.other_designs(self.project, self.v1, "des_fin_otra"), ("des_exp_cantera", "des_fin_cantera"))
        self.assertEqual(road_store.other_designs(self.project, self.v1, RAMP), ("des_exp_cantera", "des_exp_otra", "des_fin_cantera", "des_fin_otra"))
        asked = request("Pista de la cantera", layer=rd.ENTRIES_LAYER, origin="Entrada de la cantera de bancos", destination="Entrada del tajo", surface="des_exp_cantera")
        self.assertEqual(self.prepare(asked).others, ("des_exp_otra", "des_fin_otra"))


class PlatformDestinationTest(PrepareCase):
    """RF-017-03, RF-017-04, RF-015-15, D-16: el destino en una plataforma de la 015 (``P1``, ``PLT-001``: de x = 300 a 340 m, 30 m de ancho, a 112 m sobre la rampa del 4 %, creada en V01)."""

    PLATFORM = "P1"
    PLATFORM_LAYER = "gis_fea_pistas_a_p1"
    TARGET = "PLT-001"
    LATERAL = rd.dataset_of("rampa_lateral")
    """La superficie de partida de las pistas: otra que la de la plataforma (que parte de la rampa: de cada superficie parte una sola entidad)."""
    platform_uid: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.enterClassContext(registered(*prep.entity_definitions()))
        fields = model.PlatformFields(layer=rd.PLATFORMS_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho")
        asked = model.PlatformRequest(cls.PLATFORM, fields, cls.PLATFORM, RAMP, edge_angle_deg=35.0, reach_m=20.0)
        cls.clock.advance(minutes=1)
        calculation = finish(steps.platform_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid))
        stored = calculation.create()
        cls.platform_uid = str(stored.handle.uid)
        points = (("Entrada", rd.RAMP_ORIGIN), ("En P1", (320.0, 200.0)), ("Fuera de P1", (200.0, 100.0)))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(cls.PLATFORM_LAYER, "point", tuple(((rd.absolute([point], GRID),),) for _name, point in points),
                                                                    tuple(name for name, _ in points), {}))
        cls.clock.advance(minutes=1)

    def road(self, **changes: Any) -> Any:
        """Una pista de «Entrada» a ``entity:PLT-001`` de la capa de puntos de la prueba, con la plataforma como destino."""
        base = {"layer": self.PLATFORM_LAYER, "origin": "Entrada", "destination": f"entity:{self.TARGET}", "surface": self.LATERAL}
        return request("Pista a P1", **{**base, **changes})

    def test_the_destination_is_the_point_inside_the_footprint_and_the_road_rests_on_the_entity(self) -> None:
        """RF-017-03, RF-015-15, T19-c: el destino es «En P1» (el único punto de la capa en la huella de ``PLT-001``); su cota es la de la superficie de la plataforma en él
        (112 m, la de su rasante) y se anota con su origen; la pista **se apoya en ella**: ``supports``, la fila ``supports`` de los parámetros (que la operación lee) y, como entradas, su
        superficie (``supported_on``) y la tabla de su huella (``support_footprint``). Nada se escribe y cabe en el plazo."""
        before = self.state()
        started = time.perf_counter()
        prepared = self.prepare(self.road())
        total = time.perf_counter() - started
        self.assertEqual(self.state(), before)
        self.assertLessEqual(total, BUDGET_S, f"preparar tardó {total:.3f} s")
        self.assertEqual(prepared.supports, (self.TARGET,))
        self.assertEqual(prepared.job.geometry.destination, absolute((320.0, 200.0)))
        self.assertAlmostEqual(prepared.job.end_level_m, 112.0, places=9)
        rows = {row.param: row for row in prepared.rows}
        self.assertEqual((rows["supports"].value, rows["supports"].source_kind, rows["destination"].value), (self.TARGET, "algorithm", f"entity:{self.TARGET}"))
        self.assertIn(self.TARGET, rows["end_level_m"].source)
        used = {(use.item, str(use.role)) for use in prepared.start.inputs}
        surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, self.PLATFORM)
        table = provenance.dataset_name(provenance.ENTITY_TABLE, self.PLATFORM)
        self.assertIn((surface, provenance.SUPPORTED_ON_ROLE), used)
        self.assertIn((table, provenance.SUPPORT_FOOTPRINT_ROLE), used)
        self.assertIn(f"{KEY}supports", prepared.start.params)
        self.assertEqual(prepared.start.settings["fields"], {"name_field": "nombre"})
        self.assertIn(PROFILE, prepared.profile.code)

    def test_no_point_or_several_points_in_the_footprint(self) -> None:
        """RF-017-04, T19-c: una capa sin ningún punto en la huella de la plataforma se rechaza (``des.road_destination_not_in_entity``) y una con varios, también
        (``des.road_destination_ambiguous``: «Destino rampa» y «Punto en P1» caen en ella): no se elige uno por la persona."""
        error = self.refused(request("Pista a P1", origin="Origen rampa", destination=f"entity:{self.TARGET}", layer=rd.POINTS_LAYER, surface=self.LATERAL),
                             "des.road_destination_ambiguous")
        self.assertEqual((error.values["target"], error.values["points"]), (self.TARGET, 2))
        only_origin = self.road(origin="En P1")
        error = self.refused(only_origin, "des.road_destination_not_in_entity")
        self.assertEqual((error.values["field"], error.values["target"]), (f"{KEY}destination", self.TARGET))

    def test_an_entity_that_does_not_exist(self) -> None:
        """RF-015-15, RF-017-03: apoyarse en una entidad que la versión no tiene se rechaza con ``des.entity_supports_unknown``, nombrándola."""
        error = self.refused(self.road(destination="entity:PLT-009"), "des.entity_supports_unknown")
        self.assertEqual(error.values["target"], "PLT-009")

    def test_the_chain_a_road_starts_from_the_surface_of_a_platform(self) -> None:
        """RF-017-05, D-16, RF-015-04: una pista parte de la superficie que deja una entidad (``entity:PLT-001``); de cada superficie parte una sola entidad: una pista que parte de la
        misma que la plataforma (la rampa) se rechaza con ``des.entity_start_taken``; y la partida por defecto, sin cantera, es la última de la cadena (con su conflicto: nadie parte
        aún de ella)."""
        found = road_store.default_start(self.project, self.v1)
        self.assertEqual((found.ref, found.kind, found.name, found.conflict), (f"entity:{self.TARGET}", "chain_tail", self.PLATFORM, None))
        prepared = self.prepare(request("Pista desde P1", origin="Origen rampa", destination="Destino rampa", surface=f"entity:{self.TARGET}"))
        self.assertEqual((prepared.start_ref, prepared.start_surface), (f"entity:{self.TARGET}", provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, self.PLATFORM)))
        self.assertIn(prepared.start_surface, [use.item for use in prepared.start.inputs if str(use.role) == provenance.SURFACE_ROLE])
        error = self.refused(request("Otra pista", origin="Origen rampa", destination="Destino rampa", surface=RAMP), "des.entity_start_taken")
        self.assertEqual((error.values["entity"], error.values["other"]), ("Otra pista", self.PLATFORM))
