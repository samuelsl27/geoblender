# SPDX-License-Identifier: GPL-3.0-or-later
"""Ramales, apoyo retirado y el relleno posterior con la pista, con el proyecto (spec 017, T24; HU-017-1 y HU-017-2; RF-017-03 y RF-017-01; RF-015-04, RF-015-15, RF-015-16, RF-015-17 y RF-015-18; CE-017-08;
E5; plan 017 §5.2.3 «Dependencias» y §5.7 P-5; D-16 y D-24), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_chain.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01 y el perfil de referencia (**solo de las pruebas**), y la cadena de la T21 calculada en V01 —la plataforma
``P1`` (``PLT-001``), la «Pista a P1» (``RDW-001``: destino en ella), el «Ramal» (``RDW-002``: origen en el eje de la anterior, ``RDW-001@100``) y la «Relleno sobre la calzada» (``PLT-002``)—. **El marco
de la 015 con la pista, sin una regla nueva del grafo** (P-5): lo que hacen estas pruebas es comprobar que lo de siempre vale para ella:

- **Un ramal** (:class:`BranchTest`, RF-017-03, RF-015-04, RF-015-15, D-16): es la sucesora de la pista principal en la cadena, un segundo ramal desde la misma superficie se rechaza, y lo que se le apoya
  es **una sola lista** con el ramal y el relleno posterior sobre la calzada, con el volumen de la cuenta a mano (≤ 10⁻⁹ relativo).
- **Cambiar la plataforma de destino** (:class:`TargetPlatformTest`, RF-015-16, CE-017-08): la pista, el ramal y el relleno quedan obsoletos **en cascada con su causa** y «Recalcular lo obsoleto» los repite
  en orden.
- **Descartar la pista principal** (:class:`DiscardMainRoadTest`, RF-015-17, D-24, E5): una sola lista antes, «apoyo retirado» en el ramal y en el relleno, «Recalcular lo obsoleto» sin recalcularlos y qué
  dice su resumen, lo independiente que sí se rehace, y dar por bueno **lo que se apoya sin partir de ella** (el relleno) con su motivo y no lo que parte de su superficie (el ramal).
- **Rehacerlo** (:class:`RemakeBranchTest`) **o descartarlo** (:class:`DiscardBranchTest`): las otras dos salidas de RF-015-17.
- **Dar por buena una pista** (:class:`ReleasedRoadTest`, :class:`PointOfTheRoadTest`): la que solo **declara** que se apoya en la pista descartada se repite sin esa entrada; la que toma de ella su origen,
  no (``des.road_release_geometry``).
- **Lo que va antes de la pista en la cadena** (:class:`UpstreamFillTest`): un relleno que parte antes que la pista no se apoya en ella y no pierde nada si se descarta; cambiado, la pista solo queda obsoleta.
- **Traerlo a otra versión** (:class:`BringAfterDiscardTest`, RF-015-18, CE-017-08): lo descartado no se trae y lo que dependía de ello llega sin calcular y con el aviso.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.milestone_road_create import FAMILIES, FILL, FIRST, PLATFORM, SECOND
from tests.unit.design.milestone_road_recompute import PROFILE_STEP, RecomputeCase, finish_steps
from tests.unit.design.test_entity_discard import DiscardCase
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import BY, GRID, request

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
events = import_geoblender("core.project.events")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")

DesignError = messages.DesignError
Kind, State = entities.EntityKind, entities.EntityState
Status = recompute_mod.UnitStatus
SUPPORTED_ON, SURFACE = provenance.SUPPORTED_ON_ROLE, provenance.SURFACE_ROLE
TOL = 1e-9
MIN_THICKNESS_M = 0.02
"""El espesor mínimo de la 012 (``res.verify.min_thickness_m``, D-6: 0,02 m por defecto) que usa la detección de lo apoyado: el proyecto de pruebas no lo cambia."""
WHY = "La pista principal se hace por otro trazado"
GOOD = "El relleno ya está hecho sobre la calzada y no se rehace"
LATERAL = rd.dataset_of("rampa_lateral")
"""Otra superficie que la de la cadena (la plataforma parte de la rampa, la pista de ella y el ramal de la pista): de cada superficie parte una sola entidad."""
EDGE_ANGLE = design_params.entity_key("PLT-001", "edge_angle_deg")
"""El ángulo del borde de ``P1`` (35°): cambiarlo cambia su superficie, y con ella lo que la pisa."""
SERVICE, OTHER = "Pista de servicio", "Otro ramal"
CHAIN = ("PLT-001", "RDW-001", "RDW-002", "PLT-002")


def surface_of(name: str) -> str:
    """El nombre del dato de la superficie entera (``des_psf_``) de la entidad ``name``."""
    return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name)


def footprint_of(name: str) -> str:
    """El nombre del dato de la huella (``des_epr_``) de la entidad ``name``."""
    return provenance.dataset_name(provenance.ENTITY_TABLE, name)


class ChainCase(DiscardCase, RecomputeCase):
    """La cadena de la T21 en V01 y las ayudas de lo que se mira (estados, lo que se escribió, la cuenta a mano de lo apoyado en la pista principal)."""

    chain: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.chain = cls.build_chain()

    def snapshot(self) -> dict[str, Any]:
        """Todo lo que podrían escribir descartar, dar por bueno o recalcular lo que espera: operaciones, entradas y salidas, cifras, parámetros, datos, eventos y los ficheros de ``rasters/``."""
        return {
            "operations": self.query("SELECT uid, status, superseded_by FROM gb_operation ORDER BY fid"),
            "io": self.query("SELECT operation_uid, direction, item_uid, role FROM gb_operation_io ORDER BY fid"),
            "figures": self.query("SELECT operation_uid, key, scope, value FROM gb_figure ORDER BY fid"),
            "parameters": self.query("SELECT key, scope_uid, value, rev FROM gb_parameter ORDER BY rowid"),
            "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"),
            "events": self.query("SELECT kind, message FROM gb_event ORDER BY fid"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def supported_by_hand(self, result: str, start: str) -> float:
        """Lo que la entidad ``result`` (que parte de la superficie de ``start``) apoya en la pista principal, **a mano**: ``Σ (resultado − máx(partida, pista))·área`` en las celdas de su huella donde pasa
        del espesor mínimo de la 012 (RF-015-15), sin el código bajo prueba."""
        found, begun, road = (self.grid_of(surface_of(name)) for name in (result, start, FIRST))
        footprint = entity_store.runs_mask(json.loads(self.table(FIRST, provenance.ENTITY_TABLE)[0]["footprint"]), GRID.shape)
        with np.errstate(invalid="ignore"):
            thickness = found - np.maximum(begun, road)
            counted = footprint & (thickness > MIN_THICKNESS_M)
        return float(thickness[counted].sum()) * GRID.cell_area

    def states_now(self) -> dict[str, Any]:
        return {code: state for code, state in sorted(self.states().items())}

    def release(self, target: str, entity: str | None, reason: str = GOOD) -> tuple[Any, Any]:
        """«Dar por bueno» ``target`` sin su apoyo en ``entity``, un minuto después de lo anterior: la operación nueva y lo que dejó."""
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, target, entity, reason=reason, decided_by=BY)
        return handle, finish_steps(work)


class BranchTest(ChainCase):
    """RF-017-03, RF-015-04, RF-015-15, D-16: un ramal es otra pista con su origen en el eje de la anterior."""

    def test_a_the_branch_is_the_successor_of_the_road_and_starts_from_its_surface(self) -> None:
        """RF-017-03, RF-015-04, D-16: el ramal (``RDW-002``) parte de la superficie de la pista principal (su operación la consume con el papel ``surface``) y es **su sucesora en la cadena**: P1, la pista, el
        ramal y el relleno; su origen es el punto del eje de la pista a 100 m."""
        registry = entities.registry(self.project, self.v1.uid)
        records = [entry.record for entry in registry]
        self.assertEqual([item.code for item in entities.chain_of(records, "PLT-001")], list(CHAIN))
        self.assertEqual(entities.successor_of(records, "RDW-001").code, "RDW-002")
        self.assertEqual(registry.get("RDW-002").record.start, "entity:RDW-001")
        self.assertIn((surface_of(FIRST), SURFACE), self.inputs(self.current("RDW-002")))
        self.assertEqual(self.table(SECOND, provenance.ROAD_AXIS_TABLE)[0]["station_m"], 0.0)
        axis = {row["station_m"]: row for row in self.table(FIRST, provenance.ROAD_AXIS_TABLE)}
        branch = self.table(SECOND, provenance.ROAD_AXIS_TABLE)[0]
        self.assertEqual((branch["x"], branch["y"]), (axis[100.0]["x"], axis[100.0]["y"]), "el ramal sale del punto del eje de la pista a 100 m")

    def test_b_a_second_branch_from_the_same_surface_is_refused_and_writes_nothing(self) -> None:
        """RF-015-04, D-16: de cada superficie parte como mucho una entidad: un segundo ramal que parta de la superficie de la pista principal (que ya tiene al primero) se rechaza con
        ``des.entity_start_taken`` nombrando el ramal que la ocupa, sin escribir nada."""
        before = self.snapshot()
        asked = request(OTHER, layer=rd.POINTS_LAYER, origin="RDW-001@100", destination="Destino del ramal", surface="entity:RDW-001")
        with self.assertRaises(DesignError) as caught:
            self.calculate_in(asked)
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        self.assertIn(SECOND, caught.exception.text)
        self.assertEqual(self.snapshot(), before)

    def test_c_what_rests_on_the_road_is_one_list_with_the_branch_and_the_fill_with_their_volume(self) -> None:
        """RF-015-15, RF-017-03, CE-017-08: lo que se apoya en la pista principal es **una sola lista**, por orden de registro: el ramal (parte de su superficie y se apoya en ella: su origen está en su eje) y
        el relleno posterior sobre la calzada (se apoya con su volumen, la cuenta a mano de ``resultado − máx(partida, pista)`` sobre su huella, a ≤ 10⁻⁹ relativo); y la cifra ``des.supported_m3`` del relleno es
        la de la lista."""
        found = entities.dependents(self.project, self.v1.uid, "RDW-001")
        self.assertEqual([(row.name, row.op_type, row.entity, row.roles) for row in found],
                         [(SECOND, provenance.ROAD, "RDW-002", (SUPPORTED_ON, SURFACE)), (FILL, provenance.PLATFORM, "PLT-002", (SUPPORTED_ON,))])
        for row, (result, start) in zip(found, ((SECOND, FIRST), (FILL, SECOND)), strict=True):
            by_hand = self.supported_by_hand(result, start)
            self.assertGreater(by_hand, 0.0, result)
            self.assertAlmostEqual(row.volume_m3, by_hand, delta=TOL * by_hand, msg=result)
        (expected,) = provenance.supported_figures(FILL, {"RDW-001": found[1].volume_m3})
        self.assertIn((expected.value, dict(expected.scope)), [(value, scope) for key, value, scope in self.figures_of(self.current("PLT-002")) if key == "des.supported_m3"])


    def test_d_the_other_designs_of_a_road_leave_out_what_it_left_and_what_starts_from_it(self) -> None:
        """RF-017-05 (b), RF-017-03, RF-015-02 (T24; la partida rehecha): de los otros diseños con que se compara la partida de una pista **no es ninguno lo que dejó ella ni lo que parte de ello** (el ramal y el
        relleno sobre su calzada dependen de ella: anotarlos como entrada la haría depender de lo que depende de ella). Con una partida que nada une a lo demás en el grafo, la última superficie de la
        cadena (el relleno) es «otro diseño»; con ``own`` —la operación que se recalcula— la del propio relleno, la del ramal, la de la pista y la de la plataforma de la que parte todo no lo son; con otra
        operación, sí."""
        start = "gis_dtm_sin_escritor"
        fill = surface_of(FILL)
        self.assertEqual(road_store.other_designs(self.project, self.v1, start), (fill,))
        self.assertEqual(road_store.other_designs(self.project, self.v1, start, own="otra-operacion"), (fill,))
        for code in CHAIN:  # el relleno es la propia operación (la primera cláusula) o parte de lo que ella dejó (la segunda)
            with self.subTest(own=code):
                self.assertEqual(road_store.other_designs(self.project, self.v1, start, own=self.current(code)), ())

    def test_e_the_origin_on_the_axis_of_a_road_makes_it_rest_on_it_but_only_the_start_puts_it_in_the_chain(self) -> None:
        """RF-017-03, D-16: el origen de una pista en el eje de la principal la hace **apoyarse** en ella (``supports``: la dependencia declarada) pero no ponerla en su cadena: solo la partida (``start``)
        lo hace; con otra partida libre (la superficie lateral) se prepara, se apoya en ``RDW-001`` y **no escribe nada**."""
        before = self.snapshot()
        free = request(OTHER, layer=rd.POINTS_LAYER, origin="RDW-001@100", destination="Destino del ramal", surface=LATERAL)
        prepared = self.prepare(free)
        self.assertEqual((prepared.start_surface, prepared.supports), (LATERAL, ("RDW-001",)))
        self.assertEqual(self.snapshot(), before, "preparar no escribe")


class TargetPlatformTest(ChainCase):
    """RF-015-16, RF-017-03, CE-017-08: cambiar la plataforma de destino deja obsoletas la pista y el ramal en cascada, con su causa, y se recalculan en orden. **En orden** (``test_a``, ``test_b``)."""

    olds: ClassVar[dict[str, str]]
    before: ClassVar[bytes]

    def test_a_changing_the_platform_makes_the_road_the_branch_and_the_fill_stale_with_the_cause(self) -> None:
        """RF-015-16, CE-017-08: cambiar el ángulo del borde de ``P1`` (35 → 30°) la deja obsoleta a ella y, **en cascada**, a la pista que llega a ella, al ramal que sale de la pista y al relleno
        posterior, las cuatro con la misma causa (el parámetro, por su nombre: «Obsoleto: cambió Ángulo de borde de la plataforma · P1»); el plan es en el orden de la cadena."""
        type(self).olds = {code: self.current(code) for code in CHAIN}
        self.change(EDGE_ANGLE, 30.0)
        for code, uid in self.olds.items():
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", EDGE_ANGLE)}, code)
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), "Obsoleto: cambió Ángulo de borde de la plataforma · P1", code)
        self.assertEqual({code: str(state) for code, state in self.states_now().items()}, dict.fromkeys(CHAIN, "stale"))
        self.assertEqual(self.recompute_plan(), [(provenance.PLATFORM,), (provenance.ROAD,), (provenance.ROAD,), (provenance.PLATFORM,)])

    def test_b_recompute_stale_repeats_them_in_order_and_with_what_is_new(self) -> None:
        """RF-015-16, RF-008-26, CE-017-08: «Recalcular lo obsoleto» repite la plataforma, la pista, el ramal y el relleno **en ese orden**, cada una como operación nueva que sustituye a la anterior; todas al
        día al terminar y la superficie de ``P1`` cambió (el borde con otro ángulo); el ramal sigue saliendo del punto del eje de la pista a 100 m."""
        platform = self.hashes(surface_of(PLATFORM))
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in made], [provenance.PLATFORM, provenance.ROAD, provenance.ROAD, provenance.PLATFORM])
        self.assertEqual([self.supersedes(uid) for uid in made], [[(self.olds[code], "done")] for code in CHAIN])
        self.assertEqual({code: self.current(code) for code in CHAIN}, dict(zip(CHAIN, made, strict=True)))
        self.assertNotEqual(self.hashes(surface_of(PLATFORM)), platform, "la superficie de P1 es otra: el borde tiene otro ángulo")
        self.assertEqual({code: str(state) for code, state in self.states_now().items()}, dict.fromkeys(CHAIN, "current"))
        self.assertEqual(self.recompute_plan(), [])
        axis = {row["station_m"]: row for row in self.table(FIRST, provenance.ROAD_AXIS_TABLE)}
        branch = self.table(SECOND, provenance.ROAD_AXIS_TABLE)[0]
        self.assertEqual((branch["x"], branch["y"]), (axis[100.0]["x"], axis[100.0]["y"]))


class DiscardMainRoadTest(ChainCase):
    """RF-015-17, D-24, E5, CE-017-08: descartar la pista principal. **En orden** (``test_a`` a ``test_f``)."""

    def test_a_the_list_before_discarding_is_one_list_with_the_branch_and_the_fill_and_writes_nothing(self) -> None:
        """RF-015-17, CE-017-08: antes de descartar la pista principal, **una sola lista** de lo que se le apoya —el ramal, que parte de su superficie y se apoya en ella, y el relleno sobre su calzada, con
        su volumen a mano—, cada fila con su nombre, su tipo y los m³ (la misma de ``entities.dependents``), en español; **no escribe nada**."""
        before = self.snapshot()
        plan = entity_store.discard_plan(self.project, self.v1.uid, "RDW-001")
        self.assertEqual(self.snapshot(), before, "la lista no escribe nada")
        self.assertEqual((plan.code, plan.name, plan.kind, plan.state, plan.calculated), ("RDW-001", FIRST, Kind.ROAD, State.CURRENT, True))
        self.assertEqual([(row.name, row.op_type, row.entity, row.roles) for row in plan.dependents],
                         [(SECOND, provenance.ROAD, "RDW-002", (SUPPORTED_ON, SURFACE)), (FILL, provenance.PLATFORM, "PLT-002", (SUPPORTED_ON,))])
        self.assertEqual(plan.dependents, entities.dependents(self.project, self.v1.uid, "RDW-001"))
        for row, (result, start) in zip(plan.dependents, ((SECOND, FIRST), (FILL, SECOND)), strict=True):
            self.assertAlmostEqual(row.volume_m3, self.supported_by_hand(result, start), delta=TOL * row.volume_m3, msg=result)
        shown = plan.lines("es")
        self.assertEqual(len(shown), 2)
        self.assertTrue(shown[0].startswith(f"{SECOND} (Pista): "), shown[0])
        self.assertTrue(shown[1].startswith(f"{FILL} (Plataforma): "), shown[1])
        self.assertTrue(all("m³ apoyados" in line for line in shown))
        with self.assertRaises(ValueError):
            entity_store.discard_plan(self.project, self.v1.uid, "RDW-009")

    def test_b_discarding_it_discards_its_four_data_deletes_nothing_and_leaves_an_event(self) -> None:
        """RF-015-17, RF-009-12, D-12: descartar la pista pone ``discarded`` los cuatro datos que escribió (la superficie, la huella, el eje y el informe) con **un evento** (``entity_discarded``: quién, por qué,
        qué datos y la lista de lo que se le apoyaba); **nada se borra** (las operaciones, las entradas, las cifras, los ficheros y las tablas siguen); la pista queda «descartada», el ramal y el relleno,
        **«apoyo retirado»**, y la plataforma de la que parte no se toca."""
        listed = entity_store.discard_plan(self.project, self.v1.uid, "RDW-001")
        before = self.snapshot()
        names = sorted(provenance.dataset_name(family, FIRST) for family in FAMILIES)
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        self.assertEqual((found.code, found.name, found.version, found.reason, found.decided_by), ("RDW-001", FIRST, "V01", WHY, BY))
        self.assertEqual(sorted(found.datasets), names)
        self.assertEqual(found.dependents, listed.dependents, "la lista que se enseñó es la que se registra")
        self.assertEqual(set(self.dataset_status(*names).values()), {"discarded"})
        after = self.snapshot()
        for what in ("operations", "io", "figures", "files"):
            self.assertEqual(after[what], before[what], what)
        self.assertEqual(len(after["datasets"]), len(before["datasets"]))
        self.assertEqual(self.query(f'SELECT count(*) FROM "{self.locator(footprint_of(FIRST))}"'), [(1,)], "su tabla sigue ahí")
        self.assertEqual(self.states_now(), {"PLT-001": State.CURRENT, "PLT-002": State.SUPPORT_REMOVED, "RDW-001": State.DISCARDED, "RDW-002": State.SUPPORT_REMOVED})
        (event,) = self.events(events.EventKind.ENTITY_DISCARDED)
        self.assertEqual((event.entity_kind, event.entity_uid), ("entity", "RDW-001"))
        self.assertEqual({key: event.data[key] for key in ("version", "entity", "name", "reason", "decided_by")}, {"version": "V01", "entity": "RDW-001", "name": FIRST, "reason": WHY, "decided_by": BY})
        self.assertEqual([(item["name"], item["type"]) for item in event.data["dependents"]], [(SECOND, provenance.ROAD), (FILL, provenance.PLATFORM)])
        self.assertEqual(sorted(event.data["datasets"]), names)

    def test_c_what_rested_on_it_says_why_in_both_languages_and_only_the_fill_can_be_given_as_good(self) -> None:
        """RF-015-17, RF-015-25 (D-12): la causa de lo que se apoyaba en la pista es «Apoyo retirado: se descartó la pista «Pista a P1»» (con su **nombre**), en español y en inglés; lo que perdió su apoyo es el
        ramal (parte de su superficie: no se puede dar por bueno) y el relleno (solo se apoya en ella: sí)."""
        for code in ("RDW-002", "PLT-002"):
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), f"Apoyo retirado: se descartó la pista «{FIRST}»", code)
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code, language="en"), f"Support removed: the haul road «{FIRST}» was discarded", code)
        retired = {row.name: row for row in entities.retired_supports(self.project, self.v1.uid)}
        self.assertEqual(list(retired), [SECOND, FILL])
        self.assertEqual([(item.code, item.name, item.roles) for item in retired[SECOND].retired], [("RDW-001", FIRST, (SUPPORTED_ON, SURFACE))])
        self.assertEqual([(item.code, item.name, item.roles) for item in retired[FILL].retired], [("RDW-001", FIRST, (SUPPORTED_ON,))])
        self.assertEqual((retired[SECOND].releasable, retired[FILL].releasable, retired[SECOND].entity, retired[FILL].entity), (False, True, "RDW-002", "PLT-002"))
        self.assertEqual(self.states_now()["PLT-001"], State.CURRENT, "la plataforma de la que parte no pierde nada")

    def test_d_recompute_stale_does_not_recompute_it_and_the_summary_says_what_it_waits_for(self) -> None:
        """RF-015-17, RF-008-26 (error 59), H3-1 de la 016: «Recalcular lo obsoleto» **no recalcula** el ramal (``core.recompute_no_successor_release``: lo que consumía se descartó y no tiene sucesor: espera
        a que se rehaga, se descarte o se dé por bueno con un motivo); lo que depende de él, el relleno, **espera con él** (ni se intenta); ninguna operación nueva; el resumen (los resultados y lo que queda)
        dice el dato descartado, en español y en inglés, y lo mismo que dice con una plataforma (015) o con un acopio (016)."""
        before = self.snapshot()
        self.assertEqual(self.recompute_plan(), [(provenance.ROAD,), (provenance.PLATFORM,)])
        self.clock.advance(minutes=1)
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        (first,) = outcome.results
        self.assertEqual((first.status, first.code, first.unit.op_types), (Status.REFUSED, "core.recompute_no_successor_release", (provenance.ROAD,)))
        self.assertEqual(dict(first.values), {"name": surface_of(FIRST)})
        self.assertIn("se descartó y no tiene sucesor", first.text())
        self.assertIn("discarded", first.text(language="en"))
        self.assertNotEqual(first.text(), first.text(language="en"))
        self.assertEqual(sum(len(result.operations) for result in outcome.results if result.status is Status.DONE), 0, "no rehace nada")
        self.assertEqual([unit.op_types for unit in outcome.remaining.units], [(provenance.ROAD,), (provenance.PLATFORM,)], "el relleno espera con el ramal")
        self.assertEqual(outcome.remaining.skipped, ())
        after = self.snapshot()
        for what in ("operations", "io", "figures", "datasets", "files"):
            self.assertEqual(after[what], before[what], f"{what}: ninguna operación nueva")
        self.assertEqual(self.recompute_plan(), [(provenance.ROAD,), (provenance.PLATFORM,)])
        self.assertEqual((self.state_of("RDW-002"), self.state_of("PLT-002")), (State.SUPPORT_REMOVED, State.SUPPORT_REMOVED))

    def test_e_what_does_not_depend_on_the_waiting_unit_is_recomputed_and_what_depends_on_it_waits(self) -> None:
        """RF-015-17, RF-008-26, H3-1 de la 016: con el ramal esperando una decisión, lo **independiente** que está obsoleto (la plataforma ``P1``, de la que parte toda la cadena, con otro ángulo de borde) **sí**
        se recalcula; el ramal se rehúsa y el relleno, que parte de su superficie, ni se intenta: el aviso del H3-1 («no rehace nada») es solo de lo que depende de la unidad que espera."""
        old = self.current("PLT-001")
        self.change(EDGE_ANGLE, 30.0)
        self.assertEqual(self.recompute_plan(), [(provenance.PLATFORM,), (provenance.ROAD,), (provenance.PLATFORM,)])
        self.clock.advance(minutes=1)
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        self.assertEqual([(result.status, result.unit.op_types) for result in outcome.results], [(Status.DONE, (provenance.PLATFORM,)), (Status.REFUSED, (provenance.ROAD,))])
        self.assertNotEqual(self.current("PLT-001"), old)
        self.assertEqual(self.supersedes(self.current("PLT-001")), [(old, "done")])
        self.assertEqual([unit.op_types for unit in outcome.remaining.units], [(provenance.ROAD,), (provenance.PLATFORM,)])
        self.assertEqual((self.state_of("PLT-001"), self.state_of("RDW-002"), self.state_of("PLT-002")), (State.CURRENT, State.SUPPORT_REMOVED, State.SUPPORT_REMOVED))

    def test_f_the_fill_can_be_given_as_good_with_a_reason_and_the_branch_cannot(self) -> None:
        """RF-015-17, A7, P-6: el ramal **parte de la superficie** de la pista descartada: sin ella no hay sobre qué repetirlo, así que no se puede dar por bueno (``des.entity_release_start``, sin escribir
        nada: se rehace sobre otra superficie o se descarta); el relleno **solo se apoya en ella**: se repite **sin esa entrada** (ni su superficie ni la tabla de su huella), con el motivo y quién en sus
        ajustes y un evento, **su salida no cambia** (los mismos hash) y deja de estar en «apoyo retirado»."""
        before = self.snapshot()
        with self.assertRaises(DesignError) as refused:
            entity_store.release_support(self.project, self.v1.uid, SECOND, "RDW-001", reason=GOOD, decided_by=BY)
        self.assertEqual(refused.exception.code, "des.entity_release_start")
        self.assertIn(SECOND, refused.exception.text)
        self.assertIn(FIRST, refused.exception.text)
        self.assertEqual(self.snapshot(), before)
        old = self.current("PLT-002")
        outputs, inputs = [(row[0], row[3]) for row in self.outputs(old)], self.inputs(old)
        handle, stored = self.release(FILL, "RDW-001")
        new = str(handle.uid)
        self.assertEqual(str(stored.handle.uid), new)
        self.assertEqual(self.supersedes(new), [(old, "done")])
        (given,) = provenance.released_supports(self.settings_of(new))
        self.assertEqual((given.entity, given.reason, given.by), ("RDW-001", GOOD, BY))
        gone = {(surface_of(FIRST), SUPPORTED_ON), (footprint_of(FIRST), provenance.SUPPORT_FOOTPRINT_ROLE)}
        self.assertLessEqual(gone, set(inputs))
        self.assertEqual(self.inputs(new), [item for item in inputs if item not in gone], "sin la superficie de la pista ni la tabla de su huella; lo demás, igual")
        self.assertEqual([(row[0], row[3]) for row in self.outputs(new)], outputs, "su salida no cambia")
        (event,) = self.events(events.EventKind.SUPPORT_RELEASED)
        self.assertEqual((event.data["entities"], event.data["reason"], event.data["decided_by"], event.data["superseded"]), (["RDW-001"], GOOD, BY, old))
        self.assertEqual([row.name for row in entities.retired_supports(self.project, self.v1.uid)], [SECOND])
        self.assertEqual([row.name for row in entities.dependents(self.project, self.v1.uid, "RDW-001")], [SECOND])
        self.assertNotEqual(self.state_of("PLT-002"), State.SUPPORT_REMOVED)
        self.assertEqual(self.state_of("RDW-002"), State.SUPPORT_REMOVED)


class RemakeBranchTest(ChainCase):
    """RF-015-17, E5: la salida de **rehacerlo**: el ramal sobre otra superficie y con otro origen, y el relleno dado por bueno. **En orden** (``test_a``, ``test_b``)."""

    old: ClassVar[str]

    def test_a_remaking_the_branch_on_another_surface_and_origin_brings_it_back(self) -> None:
        """RF-015-17, RF-017-03, RF-017-05 (b): descartada la pista principal, el ramal se **rehace** cambiando su partida (otra superficie), su origen (un punto de la capa) y su dependencia declarada
        (``supports``, que anotó al crearlo): la operación nueva sustituye a la vieja, ya no consume nada de la pista descartada **ni anota como otro diseño** el relleno que parte de lo que dejó él
        (un bucle que no se asienta), queda **al día** y deja de estar en «apoyo retirado»; el relleno, que se apoyaba en la pista descartada, sigue esperando."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        type(self).old = self.current("RDW-002")
        for param, value in (("start", LATERAL), ("origin", "Origen rampa"), ("supports", "")):
            self.change(design_params.entity_key("RDW-002", param), value)
        asked = provenance.road_request(self.settings_of(self.old), entity_store.entity_parameters(self.project, "RDW-002", version=self.v1))
        self.assertEqual((asked.start, asked.origin), (LATERAL, "Origen rampa"))
        self.clock.advance(minutes=1)
        made = finish(steps.road_run(self.project, asked, masks=self.masks_v1, version=self.v1.uid, code="RDW-002", supersedes=self.old)).create(decided_by=BY)
        new = str(made.handle.uid)
        self.assertEqual(self.supersedes(new), [(self.old, "done")])
        self.assertEqual(self.current("RDW-002"), new)
        taken = {name for name, _role in self.inputs(new)}
        self.assertEqual(taken & {surface_of(FIRST), footprint_of(FIRST), provenance.dataset_name(provenance.ROAD_AXIS_TABLE, FIRST)}, set(), "nada de la pista descartada")
        self.assertIn((LATERAL, SURFACE), self.inputs(new))
        self.assertNotIn(provenance.ROAD_OTHER_DESIGN_ROLE, [role for _name, role in self.inputs(new)], "el relleno que parte de su superficie no es otro diseño")
        self.assertEqual(self.states_now(), {"PLT-001": State.CURRENT, "PLT-002": State.SUPPORT_REMOVED, "RDW-001": State.DISCARDED, "RDW-002": State.CURRENT})
        self.assertEqual([row.name for row in entities.retired_supports(self.project, self.v1.uid)], [FILL])
        self.assertEqual([row.name for row in entities.dependents(self.project, self.v1.uid, "RDW-001")], [FILL])
        self.assertEqual([self.stale_causes(new)], [set()])

    def test_b_the_fill_is_given_as_good_and_everything_settles(self) -> None:
        """RF-015-17, RF-008-26: el relleno, que se apoyaba en la pista descartada y parte de la superficie que dejó el ramal rehecho, está obsoleto y esperando; se da por bueno con su motivo (se repite sin esa
        entrada y con la superficie nueva del ramal) y **nada queda por recalcular**: las cuatro entidades al día salvo la descartada, que es un registro."""
        self.assertEqual(self.recompute_plan(), [(provenance.PLATFORM,)])
        self.release(FILL, "RDW-001")
        self.assertEqual(self.states_now(), {"PLT-001": State.CURRENT, "PLT-002": State.CURRENT, "RDW-001": State.DISCARDED, "RDW-002": State.CURRENT})
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "RDW-001"), ())
        self.assertIn((surface_of(SECOND), SURFACE), self.inputs(self.current("PLT-002")), "parte de lo que dejó el ramal rehecho")


class DiscardBranchTest(ChainCase):
    """RF-015-17, E5: la salida de **descartarlo**. **En orden** (``test_a``)."""

    def test_a_discarding_the_branch_too_leaves_the_fill_with_no_way_to_be_given_as_good(self) -> None:
        """RF-015-17, D-12: descartada la pista principal, el ramal (que está en «apoyo retirado») se **descarta** también: su lista es la del relleno, que parte de su superficie (sin volumen); el relleno ha
        perdido su apoyo en las dos pistas y, como parte de la del ramal, no se puede dar por bueno: se rehace o se descarta; hay **dos** eventos y las dos pistas son un registro."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        plan = entity_store.discard_plan(self.project, self.v1.uid, "RDW-002")
        self.assertEqual([(row.name, row.entity, row.roles, row.volume_m3 is None) for row in plan.dependents], [(FILL, "PLT-002", (SURFACE,), True)])
        self.assertEqual(plan.lines("es"), (f"{FILL} (Plataforma): superficie de partida",))
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, "RDW-002", reason=WHY, decided_by=BY)
        self.assertEqual(sorted(found.datasets), sorted(provenance.dataset_name(family, SECOND) for family in FAMILIES))
        self.assertEqual(self.states_now(), {"PLT-001": State.CURRENT, "PLT-002": State.SUPPORT_REMOVED, "RDW-001": State.DISCARDED, "RDW-002": State.DISCARDED})
        self.assertEqual([event.data["entity"] for event in self.events(events.EventKind.ENTITY_DISCARDED)], ["RDW-001", "RDW-002"])
        (fill,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((fill.name, sorted(item.code for item in fill.retired), fill.releasable), (FILL, ["RDW-001", "RDW-002"], False))
        with self.assertRaises(DesignError) as refused:
            entity_store.release_support(self.project, self.v1.uid, FILL, None, reason=GOOD, decided_by=BY)
        self.assertEqual(refused.exception.code, "des.entity_release_start")
        self.assertIn(SECOND, refused.exception.text)


class ServiceRoadCase(ChainCase):
    """La cadena y **otra pista que parte de otra superficie** (la lateral, que ninguna entidad ocupa) y se apoya en la pista principal sin partir de la suya: ``cls.service`` (``RDW-003``)."""

    service: ClassVar[str]

    @classmethod
    def uid_of(cls, code: str) -> str:
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def own_inputs(self, uid: str) -> list[tuple[str, str]]:
        """Lo que consumió la operación ``uid`` **sin los otros diseños** de la versión (``other_design``: con la pista principal descartada, el relleno ya no tiene a la partida como ancestro en el
        grafo y la pista de otro terreno lo anota; no es lo que se prueba aquí)."""
        return [item for item in self.inputs(uid) if item[1] != provenance.ROAD_OTHER_DESIGN_ROLE]

    @classmethod
    def repeat(cls, code: str) -> str:
        """Repite la operación vigente de ``code`` como lo hace «Recalcular»: el uid de la operación nueva."""
        uid = cls.uid_of(code)
        with cls.project.read() as conn:
            op_type, settings = conn.execute("SELECT op_type, settings FROM gb_operation WHERE uid = ?", (uid,)).fetchone()
        cls.clock.advance(minutes=1)
        handle, work = store.recompute_run(recompute_mod.RecomputeRequest(cls.project, uid, op_type, json.loads(settings), (), (), version=cls.v1.uid))
        finish_steps(work)
        return str(handle.uid)


class ReleasedRoadTest(ServiceRoadCase):
    """RF-015-17, A7, P-6, RF-017-03: la «Pista de servicio» (``RDW-003``: de la superficie lateral, con su origen y su destino en la capa) **declara** que se apoya en la pista principal (``supports``: 0 m³);
    descartada esta, se da por buena sin ella con su motivo. **En orden** (``test_a`` a ``test_d``)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.service = str(cls.made(request(SERVICE, surface=LATERAL))[1].handle.uid)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(conn, design_params.entity_key("RDW-003", "supports"), "RDW-001", kind="ADOPTADO", source="Prueba de la T24", source_kind="person",
                                                           decided_by=BY, reason="Dependencia declarada", version=cls.v1.uid)
        cls.service = cls.repeat("RDW-003")

    def test_a_the_service_road_rests_on_the_main_road_without_starting_from_its_surface(self) -> None:
        """RF-015-15, RF-015-17, D-11: lo que la persona declara en ``supports`` se registra aunque no rellene nada: la pista de servicio está en la lista de lo que se apoya en la pista principal con el papel
        ``supported_on`` solo (no parte de su superficie) y **0 m³**; su operación consume la superficie y la tabla de la huella de la pista principal."""
        found = {row.entity: row for row in entities.dependents(self.project, self.v1.uid, "RDW-001")}
        self.assertEqual((found["RDW-003"].roles, found["RDW-003"].volume_m3), ((SUPPORTED_ON,), 0.0))
        self.assertLessEqual({(surface_of(FIRST), SUPPORTED_ON), (footprint_of(FIRST), provenance.SUPPORT_FOOTPRINT_ROLE)}, set(self.inputs(self.service)))
        self.assertNotIn((surface_of(FIRST), SURFACE), self.inputs(self.service))
        self.assertEqual(self.state_of("RDW-003"), State.CURRENT)

    def test_b_discarding_the_main_road_leaves_it_in_support_removed_and_it_can_be_given_as_good(self) -> None:
        """RF-015-17: descartada la pista principal, la pista de servicio queda «apoyo retirado» (solo ``supported_on``: se puede dar por buena), igual que el relleno y a diferencia del ramal."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        retired = {row.name: row for row in entities.retired_supports(self.project, self.v1.uid)}
        self.assertEqual(list(retired), [SECOND, FILL, SERVICE])
        self.assertEqual((retired[SERVICE].releasable, retired[SERVICE].entity, [(item.code, item.roles) for item in retired[SERVICE].retired]), (True, "RDW-003", [("RDW-001", (SUPPORTED_ON,))]))
        self.assertEqual(self.state_of("RDW-003"), State.SUPPORT_REMOVED)

    def test_c_giving_it_as_good_repeats_it_without_that_support_and_its_output_does_not_change(self) -> None:
        """RF-015-17, A7, P-6, RF-008-26: «dar por buena» la pista de servicio la **repite** (``recompute_road(released=…)``, sin pasar por el plan de «Recalcular lo obsoleto», que la rehúsa) **sin** la
        superficie ni la tabla de la huella de la pista descartada, con el motivo y quién en sus ajustes (``supports_released``) y un evento; **su superficie, su huella y su eje no cambian** (los mismos
        hash, y las mismas cifras) y su informe, solo por el aviso del otro diseño que ahora ve (el relleno: con la pista principal descartada ya no lo une a la partida el grafo); deja de estar en
        «apoyo retirado» y lo que dependía de ella no se recalcula."""
        old = self.current("RDW-003")
        outputs, figures, inputs = [(row[0], row[3]) for row in self.outputs(old)], self.figures_of(old), self.own_inputs(old)
        report = self.table(SERVICE, provenance.ENTITY_REPORT_TABLE)
        handle, stored = self.release(SERVICE, "RDW-001")
        new = str(handle.uid)
        self.assertEqual((str(stored.handle.uid), self.type_of(new)), (new, provenance.ROAD))
        self.assertEqual(self.supersedes(new), [(old, "done")])
        (given,) = provenance.released_supports(self.settings_of(new))
        self.assertEqual((given.entity, given.reason, given.by), ("RDW-001", GOOD, BY))
        gone = {(surface_of(FIRST), SUPPORTED_ON), (footprint_of(FIRST), provenance.SUPPORT_FOOTPRINT_ROLE)}
        self.assertLessEqual(gone, set(inputs))
        self.assertEqual(self.own_inputs(new), [item for item in inputs if item not in gone])
        self.assertEqual([(row[0], row[3]) for row in self.outputs(new)][:3], outputs[:3], "su salida no cambia: los mismos hash de la superficie, la huella y el eje")
        added = [row for row in self.table(SERVICE, provenance.ENTITY_REPORT_TABLE) if row not in report]
        self.assertEqual([row for row in report if row not in self.table(SERVICE, provenance.ENTITY_REPORT_TABLE)], [])
        self.assertEqual([json.loads(row["note"])["code"] for row in added], ["des.road_other_design_differs"], "el informe, igual salvo el aviso del otro diseño")
        self.assertEqual([(key, value) for key, value, _scope in self.figures_of(new) if key != "des.supported_m3"], [(key, value) for key, value, _scope in figures if key != "des.supported_m3"])
        self.assertNotEqual(self.state_of("RDW-003"), State.SUPPORT_REMOVED)
        self.assertEqual([row.name for row in entities.retired_supports(self.project, self.v1.uid)], [SECOND, FILL])
        (event,) = self.events(events.EventKind.SUPPORT_RELEASED)
        self.assertEqual((event.data["entities"], event.data["reason"], event.data["decided_by"], event.data["name"]), (["RDW-001"], GOOD, BY, SERVICE))

    def test_d_a_later_recompute_keeps_the_release_and_does_not_register_the_support_again(self) -> None:
        """RF-015-17, RF-015-16: un recálculo posterior de la pista de servicio (un cambio de otro valor que la deja obsoleta) **conserva** lo que dio por bueno (acumulado en sus ajustes, sin repetir la
        entidad) y el gancho no vuelve a registrar la pista descartada, aunque la persona siga declarando que se apoya en ella: ni la superficie ni la tabla de su huella son entradas."""
        self.change(PROFILE_STEP, 2.0)
        self.assertIn(("parameter_changed", PROFILE_STEP), self.stale_causes(self.current("RDW-003")))
        before = self.current("RDW-003")
        new = self.repeat("RDW-003")
        self.assertEqual(self.supersedes(new), [(before, "done")])
        (given,) = provenance.released_supports(self.settings_of(new))
        self.assertEqual((given.entity, given.reason, given.by), ("RDW-001", GOOD, BY))
        self.assertEqual([name for name, _role in self.inputs(new) if name in (surface_of(FIRST), footprint_of(FIRST))], [])
        self.assertNotEqual(self.state_of("RDW-003"), State.SUPPORT_REMOVED)
        self.assertEqual(len(self.events(events.EventKind.SUPPORT_RELEASED)), 1, "un recálculo no deja otro evento")


class PointOfTheRoadTest(ServiceRoadCase):
    """RF-015-17, RF-017-03: «Otro ramal» (``RDW-003``) parte de la superficie lateral pero su **origen está en el eje de la pista principal** (``RDW-001@100``): se apoya en ella sin partir de su superficie
    y no se puede dar por buena sin ella (toma de ella su lugar y su cota). **En orden** (``test_a``)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.service = str(cls.made(request(OTHER, layer=rd.POINTS_LAYER, origin="RDW-001@100", destination="Destino del ramal", surface=LATERAL))[1].handle.uid)

    def test_a_what_takes_its_origin_from_the_discarded_road_cannot_be_given_as_good(self) -> None:
        """RF-015-17, RF-017-03: descartada la pista principal, «Otro ramal» está en «apoyo retirado» y **ofrece** darse por bueno (solo ``supported_on``: no parte de su superficie), pero su origen es un punto del
        eje de la pista descartada: se rechaza con ``des.road_release_geometry`` nombrando la pista, el campo, el valor y la entidad (se rehace con otro origen o se descarta), **sin escribir nada**; y
        «Recalcular lo obsoleto» tampoco la recalcula."""
        self.assertIn((provenance.dataset_name(provenance.ROAD_AXIS_TABLE, FIRST), provenance.ROAD_AXIS_ROLE), self.inputs(self.service), "lee el eje de la pista principal")
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        retired = {row.name: row for row in entities.retired_supports(self.project, self.v1.uid)}
        self.assertTrue(retired[OTHER].releasable)
        self.assertEqual([(item.code, item.roles) for item in retired[OTHER].retired], [("RDW-001", (SUPPORTED_ON,))])
        before = self.snapshot()
        with self.assertRaises(DesignError) as refused:
            entity_store.release_support(self.project, self.v1.uid, OTHER, "RDW-001", reason=GOOD, decided_by=BY)
        error = refused.exception
        self.assertEqual((error.code, error.values["field"], error.values["value"]), ("des.road_release_geometry", "des.road.rdw_003.origin", "RDW-001@100"))
        self.assertIn(OTHER, error.text)
        self.assertIn(FIRST, error.text)
        self.assertIn("RDW-001@100", error.text_in("en"))
        self.assertEqual(self.snapshot(), before)
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        self.assertEqual(sum(len(result.operations) for result in outcome.results if result.status is Status.DONE), 0)
        self.assertEqual(self.snapshot()["operations"], before["operations"])


class SupportSurfaceReleaseTest(ServiceRoadCase):
    """RF-015-17, A7: la «Pista de servicio» (``RDW-003``) tiene como **superficie de apoyo** la de la pista principal (``support`` = ``entity:RDW-001``). **En orden** (``test_a``)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.service = str(cls.made(request(SERVICE, surface=LATERAL, support="entity:RDW-001"))[1].handle.uid)

    def test_a_what_has_the_discarded_surface_as_its_support_surface_cannot_be_given_as_good(self) -> None:
        """RF-015-17, A7, P-6 (como la plataforma de la 015): descartada la pista principal, la pista de servicio ofrece darse por buena (solo ``supported_on``) pero la tiene como superficie de apoyo:
        se rechaza con ``des.entity_release_support_param`` (cambie su superficie de apoyo o descártela), **sin escribir nada**."""
        self.assertIn((surface_of(FIRST), SUPPORTED_ON), self.inputs(self.service))
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        self.assertTrue({row.name: row for row in entities.retired_supports(self.project, self.v1.uid)}[SERVICE].releasable)
        before = self.snapshot()
        with self.assertRaises(DesignError) as refused:
            entity_store.release_support(self.project, self.v1.uid, SERVICE, "RDW-001", reason=GOOD, decided_by=BY)
        self.assertEqual((refused.exception.code, refused.exception.values["value"]), ("des.entity_release_support_param", "entity:RDW-001"))
        self.assertIn(SERVICE, refused.exception.text)
        self.assertEqual(self.snapshot(), before)


class UpstreamFillTest(DiscardCase, RecomputeCase):
    """RF-015-15, RF-015-17, CE-017-08: un relleno que va **antes** que la pista en la cadena (P1 → «Relleno sobre la calzada» → una pista que parte de lo que él dejó): la pista no se apoya en él ni él en la
    pista, así que descartar la pista no le quita nada y, si él cambia, la pista **solo queda obsoleta**. **En orden** (``test_a`` a ``test_c``)."""

    ROAD = "Pista tras el relleno"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        fields = model.PlatformFields(layer=rd.PLATFORMS_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho")
        cls.clock.advance(minutes=1)
        finish(steps.platform_run(cls.project, model.PlatformRequest(PLATFORM, fields, PLATFORM, rd.dataset_of("rampa"), edge_angle_deg=35.0, reach_m=20.0), masks=cls.masks_v1, version=cls.v1.uid)).create()
        cls.clock.advance(minutes=1)
        finish(steps.platform_run(cls.project, model.PlatformRequest(FILL, fields, FILL, "entity:PLT-001", mode="cut_fill", edge_angle_deg=35.0, reach_m=20.0), masks=cls.masks_v1, version=cls.v1.uid)).create()
        cls.clock.advance(minutes=1)
        cls.made(request(cls.ROAD, surface="entity:PLT-002"))

    def test_a_the_fill_before_the_road_is_where_it_starts_from_and_nothing_rests_on_the_road(self) -> None:
        """RF-015-15, RF-017-03, D-16: la pista parte de la superficie del relleno (papel ``surface``, sin volumen: ella corta lo que el relleno subió, no rellena sobre él) y **nada se apoya en la pista**; el
        relleno no se apoya en ella (es lo anterior en la cadena)."""
        self.assertEqual([(row.name, row.roles, row.volume_m3) for row in entities.dependents(self.project, self.v1.uid, "PLT-002")], [(self.ROAD, (SURFACE,), None)])
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "RDW-001"), ())
        self.assertEqual([(row.name, row.roles) for row in entities.dependencies_of(self.project, self.v1.uid, "RDW-001")], [(FILL, (SURFACE,))])
        records = [entry.record for entry in entities.registry(self.project, self.v1.uid)]
        self.assertEqual([item.code for item in entities.chain_of(records, "PLT-001")], ["PLT-001", "PLT-002", "RDW-001"])

    def test_b_changing_the_fill_leaves_the_road_only_stale_and_recomputing_repeats_both_in_order(self) -> None:
        """RF-015-16, RF-008-26, CE-017-08: cambiar el relleno lo deja obsoleto a él y a la pista que parte de su superficie, **solo obsoleta** («Obsoleto: …», con su causa, y no «apoyo retirado»);
        «Recalcular lo obsoleto» las repite en orden (el relleno y la pista) y al terminar nada queda por recalcular."""
        key = design_params.entity_key("PLT-002", "edge_angle_deg")
        olds = {code: self.current(code) for code in ("PLT-002", "RDW-001")}
        self.change(key, 30.0)
        self.assertEqual(self.stale_causes(olds["RDW-001"]), {("parameter_changed", key)})
        self.assertTrue(entities.stale_reason(self.project, self.v1.uid, "RDW-001").startswith("Obsoleto: cambió "))
        self.assertEqual({code: str(state) for code, state in self.states().items()}, {"PLT-001": "current", "PLT-002": "stale", "RDW-001": "stale"})
        self.assertEqual(self.recompute_plan(), [(provenance.PLATFORM,), (provenance.ROAD,)])
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in made], [provenance.PLATFORM, provenance.ROAD])
        self.assertEqual([self.supersedes(uid) for uid in made], [[(old, "done")] for old in olds.values()])
        self.assertEqual(self.recompute_plan(), [])

    def test_c_discarding_the_road_takes_nothing_from_the_fill_before_it(self) -> None:
        """RF-015-17: descartar la pista que va después del relleno no deja nada en «apoyo retirado» (ni el relleno ni la plataforma) ni nada por recalcular: su lista es la de lo que se le apoyaba, vacía."""
        plan = entity_store.discard_plan(self.project, self.v1.uid, "RDW-001")
        self.assertEqual(plan.dependents, ())
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        self.assertEqual({code: str(state) for code, state in self.states().items()}, {"PLT-001": "current", "PLT-002": "current", "RDW-001": "discarded"})
        self.assertEqual(self.recompute_plan(), [])


class BringAfterDiscardTest(ChainCase):
    """RF-015-18, RF-015-17, RF-017-03, CE-017-08: traer a otra versión lo que dejó descartar la pista principal. **En orden** (``test_a``)."""

    def test_a_what_was_discarded_is_not_brought_and_what_depended_on_it_arrives_uncalculated_with_the_notice(self) -> None:
        """RF-015-18, D-12, C-4: descartada la pista principal, traer V01 a V02 trae la plataforma, el ramal y el relleno **sin calcular** y sin ningún resultado, y **no** trae la descartada (pedirla se rechaza con
        ``des.entity_bring_discarded``); lo que se apoyaba en ella llega sin valor en lo que la nombraba, con el aviso de cada uno (la partida, el origen y lo declarado); V01 no cambia."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY)
        before = self.states_now()
        operations = self.query("SELECT uid, status, superseded_by FROM gb_operation ORDER BY uid")
        with self.assertRaises(DesignError) as asked:
            entity_store.bring_entities(self.project, "V01", "V02", codes=["RDW-001"])
        self.assertEqual(asked.exception.code, "des.entity_bring_discarded")
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual(sorted((item.source_code, item.code) for item in found.entities), [("PLT-001", "PLT-001"), ("PLT-002", "PLT-002"), ("RDW-002", "RDW-002")])
        self.assertEqual({entry.record.code: str(entry.record.state) for entry in entities.registry(self.project, self.v2.uid)}, dict.fromkeys(("PLT-001", "PLT-002", "RDW-002"), "uncalculated"))
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' ESCAPE '!'", self.v2.uid), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ?", self.v2.uid), [(0,)])
        codes = [notice.code for notice in found.notices]
        for lost in ("des.entity_bring_start_lost", "des.road_bring_origin_lost", "des.entity_bring_supports_lost"):
            self.assertIn(lost, codes)
        self.assertEqual(self.states_now(), before)
        self.assertEqual(self.query("SELECT uid, status, superseded_by FROM gb_operation ORDER BY uid"), operations, "V01 no cambia")


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
