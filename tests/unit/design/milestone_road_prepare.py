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
- **Los parámetros de la ruta** (:class:`RouteGuardsTest`, RF-017-04, RF-017-10, RF-017-12, RNF-017-07; B-3 y B-5 de la verificación única, T41): preparando de verdad, el paso de cota que da más de 2.000 niveles a
  cada lado, el origen y el destino en el mismo nodo de la malla y el aviso de la memoria de un presupuesto de estados de más del doble del de por defecto; los comprobadores puros son de ``test_road_prepare``.
- **Las zonas «preferible no afectar»** (:class:`AvoidZoneTest`, RF-017-06; S-2 de la verificación única, T42): preparando de verdad, una zona de peso 1 llega al trabajo con sus celdas aparte del
  peso (``RoadJob.avoid_zone``), y las cuatro construcciones de ``RoadJob`` del dominio le dan la zona junto al peso.

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


class RouteGuardsTest(PrepareCase):
    """B-3 y B-5 de la verificación única (T41; RF-017-04, RF-017-10, RF-017-12; RNF-017-07) **preparando de verdad** sobre el proyecto: el paso de cota que da demasiados niveles, el origen y el destino en el
    mismo nodo de la malla y el aviso de la memoria de un presupuesto de estados grande; los comprobadores puros son de ``test_road_prepare.RouteGuardsTest`` (el «verde»)."""

    def test_preparing_rejects_a_level_step_that_gives_too_many_levels(self) -> None:
        """RF-017-04, RF-017-10, RNF-017-06 (B-5 de la verificación única, T41): con H = 14 m, un paso de cota de 0,0001 m (140.000 niveles a cada lado: 108 s en una sola llamada y 424 MiB) se rechaza al
        preparar, sin calcular nada, con el campo (``level_step_m``), el valor, los niveles que saldrían, el tope (2.000) y **el paso mínimo para esa altura** (0,007 m); los 50 niveles de la referencia (14 m,
        0,28 m) y el límite exacto (0,007 m: 2.000 niveles) se preparan."""
        error = self.refused(request(max_cut_fill_m=14.0, level_step_m=0.0001), "des.road_level_step_small")
        self.assertEqual((error.values["field"], error.values["value"]), (f"{KEY}level_step_m", 0.0001))
        self.assertEqual((error.values["height"], error.values["levels"], error.values["limit"], error.values["minimum"]), (14.0, 140_000, 2000, 0.007))
        for text in (error.text, error.text_in("en")):
            self.assertIn("0,007" if text is error.text else "0.007", text)
        self.assertEqual(self.prepare(request(max_cut_fill_m=14.0, level_step_m=0.28)).job.route.level_step_m, 0.28)
        self.assertEqual(self.prepare(request(max_cut_fill_m=14.0, level_step_m=0.007)).job.route.level_step_m, 0.007)

    def test_preparing_rejects_two_points_in_the_same_node_of_the_mesh(self) -> None:
        """RF-017-04, RF-017-12 (B-3 de la verificación única, T41): el origen y el destino que caen en el mismo nodo de la malla de la ruta (con una malla de 400 m, la rejilla entera: un nodo) se rechazan al
        preparar con ``des.road_same_node`` —la capa, la pista, el campo ``destination``, el valor y la malla—, nunca con un ``ValueError``; con la malla de la referencia (4 m) no."""
        error = self.refused(request(mesh_m=400.0), "des.road_same_node")
        self.assertEqual((error.values["field"], error.values["value"], error.values["mesh"]), (f"{KEY}destination", "Destino rampa", 400.0))
        self.assertEqual(error.values["layer"], rd.POINTS_LAYER)
        self.assertIn("400 m", error.text)
        self.assertEqual(self.prepare(request()).job.route.mesh_m, 4.0)

    def test_preparing_carries_the_memory_notice_of_a_big_search_budget(self) -> None:
        """RF-017-10, RNF-017-07 (B-5 de la verificación única, T41): un presupuesto de estados de 20 M (admite hasta 10⁹) deja entre los avisos de la partida ``des.road_budget_memory`` con la memoria que puede
        ocupar (≈ 2,6 GiB con 140 bytes por estado visto), que no impide crearla; con el de la referencia, ninguno."""
        found = [notice for notice in self.prepare(request(search_budget=20_000_000)).notices if notice.code == "des.road_budget_memory"]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].values["entity"], found[0].values["budget"]), ("Pista de la rampa", 20_000_000))
        self.assertAlmostEqual(found[0].values["memory"], 2.6, places=1)
        self.assertEqual([notice.code for notice in self.prepare(request()).notices if notice.code == "des.road_budget_memory"], [])


class AvoidZoneTest(PrepareCase):
    """S-2 de la verificación única (T42; RF-017-06) **preparando de verdad**: las celdas de una zona «preferible no afectar» llegan al trabajo aparte del peso (también las de peso 1), en la preparación
    y en la reproducción de lo congelado; la pieza pura es de ``test_road_prepare.PureTest``."""

    def test_a_zone_of_weight_1_reaches_the_job_apart_from_the_weight(self) -> None:
        """RF-017-06, S-2: con una zona «preferible no afectar» de peso 1 en las máscaras de V01 (el proyecto no tiene ninguna), el trabajo preparado lleva el peso (todo 1) **y** las celdas de la
        zona (``avoid_zone``: 800 celdas); con otra de peso 3 encima, el peso 3 en las suyas y la unión de las dos como zona; sin zonas, ni peso ni zona."""
        zone = np.zeros(GRID.shape, dtype=bool)
        zone[40:60, 40:80] = True
        heavy = np.zeros(GRID.shape, dtype=bool)
        heavy[70:80, 40:50] = True

        def one(self: Any) -> dict[str, Any]:
            return {"Encinar": (mock.Mock(mask=lambda shape: zone), 1.0)}

        def two(self: Any) -> dict[str, Any]:
            return {"Encinar": (mock.Mock(mask=lambda shape: zone), 1.0), "Franja": (mock.Mock(mask=lambda shape: heavy), 3.0)}

        kind = type(self.masks_v1)
        with mock.patch.object(kind, "avoid_weights", one):
            light = self.prepare(request()).job
        with mock.patch.object(kind, "avoid_weights", two):
            both = self.prepare(request()).job
        np.testing.assert_array_equal(light.avoid_weight, np.ones(GRID.shape))
        np.testing.assert_array_equal(light.avoid_zone, zone)
        self.assertEqual(int(light.avoid_zone.sum()), 800)
        np.testing.assert_array_equal(both.avoid_weight, np.where(heavy, 3.0, 1.0))
        np.testing.assert_array_equal(both.avoid_zone, zone | heavy)
        plain = self.prepare(request()).job
        self.assertEqual((plain.avoid_weight, plain.avoid_zone), (None, None))

    def test_every_road_job_of_the_domain_carries_the_zone_with_the_weight(self) -> None:
        """RF-017-06, S-2: las cuatro construcciones de ``RoadJob`` del dominio (preparar, preparar «Proponer», reproducir la pista y reproducir el trazado) le dan la zona junto al peso: sin ella
        el trabajo la deduce de ``peso > 1`` y una zona de peso 1 se pierde en silencio (es lo que pasaba); se lee del código, sin proyecto."""
        import ast
        import pathlib

        root = pathlib.Path(road_store.__file__).parent
        found = 0
        for name in ("road_store.py", "reproduce.py"):
            for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RoadJob":
                    found += 1
                    with self.subTest(file=name, line=node.lineno):
                        self.assertTrue(any(keyword.arg == "avoid_zone" for keyword in node.keywords) or len(node.args) >= 14, "RoadJob sin la zona")
        self.assertEqual(found, 4)
