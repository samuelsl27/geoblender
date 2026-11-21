# SPDX-License-Identifier: GPL-3.0-or-later
"""Ramales, apoyo retirado y el relleno posterior con la pista, **sin proyecto** (spec 017, T24; HU-017-1 y HU-017-2; RF-017-03 y RF-017-01; RF-015-04, RF-015-15, RF-015-16 y RF-015-17; CE-017-08;
plan 017 §5.2.3 «Dependencias» y §5.7 P-5; D-16 y D-24), el «verde» de ``milestone_road_chain.py`` (que lo hace con el proyecto en la rejilla de 2 m):

- **Un ramal es otra pista con su origen en el eje de la anterior** (:class:`BranchChainTest`, RF-017-03, RF-015-04, D-16): la **sucesora en la cadena** (parte de la superficie que deja la principal),
  de cada superficie parte una sola entidad (un segundo ramal desde la misma, ``des.entity_start_taken``) y una pista descartada es un registro que ya no sigue a nadie pero de la que sí se sabe de quién
  partía (lo que dice «apoyo retirado»); una pista no se apoya en lo que parte de la suya (un ciclo).
- **Un relleno posterior sobre la calzada se apoya en la pista con su volumen** (:class:`FillOnTheRoadTest`, RF-015-15, P-5): ``detect_supports`` con la superficie entera (``des_psf_``) y la huella de la
  sección (``des_epr_``) **de una pista calculada**, a ≤ 10⁻⁹ relativo de la cuenta a mano; lo que solo arrastra el terreno sobre una calzada en desmonte, no cuenta (P-5).
- **Qué se puede dar por bueno sin su entidad** (:class:`ReleaseBlockerTest`, RF-015-17; «una sola lista» y «apoyo retirado» son los del marco, sin regla nueva del grafo: P-5): la pista cuyo origen, destino o
  superficie de apoyo **es** la entidad que se descartó no se puede repetir sin ella (su geometría sale de ella): ``entity_store._release_blocker``.
- **Dar por buena una pista** (:class:`ReleasedRoadTest`, RF-015-17): ``recompute_road`` ya no dice «es de la T24»: acepta lo que se suelta y lo pasa a la operación nueva.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.design.test_road_operation import COMMON, GRID, last, ramp_job

core_recompute = import_geoblender("core.provenance.recompute")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
road_store = import_geoblender("design.road_store")

Kind = entities.EntityKind
State = entities.EntityState
TOL = 1e-9


def chain(**states: Any) -> list[Any]:
    """P1 → «Pista a P1» (``RDW-001``) → «Ramal» (``RDW-002``) → «Relleno sobre la calzada» (``PLT-002``): la cadena de CE-017-08, con el estado de cada código de ``states`` (el resto, al día)."""
    def record(code: str, name: str, kind: Any, start: str) -> Any:
        return entities.EntityRecord(code, name, kind, start, state=states.get(code.replace("-", "_"), State.CURRENT))

    return [record("PLT-001", "P1", Kind.PLATFORM, "gis_dtm_rampa"), record("RDW-001", "Pista a P1", Kind.ROAD, "entity:PLT-001"),
            record("RDW-002", "Ramal", Kind.ROAD, "entity:RDW-001"), record("PLT-002", "Relleno sobre la calzada", Kind.PLATFORM, "entity:RDW-002")]


class BranchChainTest(unittest.TestCase):
    """RF-017-03, RF-015-04, D-16, D-24: la red de pistas es una cadena y cada ramal parte de la superficie que deja la pista anterior."""

    def test_a_the_branch_is_the_successor_of_the_road_in_the_chain(self) -> None:
        """RF-017-03, D-16: el ramal (``RDW-002``, de la superficie de la pista, con su origen en el eje de ``RDW-001``) es **la sucesora** de la pista principal; la cadena desde la plataforma es P1, la pista, el
        ramal y el relleno, y su cola, el relleno: la superficie de diseño de la cadena."""
        records = chain()
        self.assertEqual(entities.successor_of(records, "RDW-001").code, "RDW-002")
        self.assertEqual(entities.predecessor_of(records, "RDW-002").code, "RDW-001")
        self.assertEqual([item.code for item in entities.chain_of(records, "PLT-001")], ["PLT-001", "RDW-001", "RDW-002", "PLT-002"])
        self.assertEqual([item.code for item in entities.chain_tails(records)], ["PLT-002"])
        branch = records[2]
        self.assertEqual((branch.kind, entities.refers_to("RDW-001@100"), entities.ref_code(branch.start)), (Kind.ROAD, "RDW-001", "RDW-001"))

    def test_b_a_second_branch_from_the_same_surface_is_refused(self) -> None:
        """RF-015-04, D-16: de cada superficie parte como mucho una entidad: un segundo ramal que parta de la superficie de la pista principal ya tiene dueño (``RDW-002``), y cuando los datos lo dan dos veces,
        la cadena lo rechaza (``des.entity_start_taken``) con la otra entidad; una descartada es un registro y no ocupa nada."""
        records = chain()
        taken = entities.start_conflict(records, "entity:RDW-001")
        self.assertEqual(taken.code, "RDW-002")
        twice = [*records, entities.EntityRecord("RDW-003", "Otro ramal", Kind.ROAD, "entity:RDW-001")]
        with self.assertRaises(messages.DesignError) as caught:
            entities.check_chain(twice)
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        self.assertIn("Ramal", caught.exception.text)
        self.assertIsNone(entities.start_conflict(chain(RDW_002=State.DISCARDED), "entity:RDW-001"), "una descartada es un registro")

    def test_c_a_discarded_road_follows_nobody_but_remembers_where_its_branch_started(self) -> None:
        """RF-015-17, D-24: descartada la pista principal (un registro), el ramal sigue sabiendo de qué superficie partía (lo que dice «apoyo retirado») pero **ninguna descartada sigue a nadie**: la cadena de P1 acaba
        en P1 y la del ramal abre otra, con el relleno por cola."""
        records = chain(RDW_001=State.DISCARDED)
        self.assertEqual(entities.predecessor_of(records, "RDW-002").code, "RDW-001")
        self.assertEqual([item.code for item in entities.chain_of(records, "PLT-001")], ["PLT-001"])
        self.assertEqual([item.code for item in entities.chain_tails(records)], ["PLT-001", "PLT-002"])
        self.assertIsNone(entities.successor_of(records, "PLT-001"), "lo que parte de una descartada no sigue a la que la precede")

    def test_d_a_road_does_not_rest_on_what_starts_from_its_own_surface(self) -> None:
        """RF-015-15, D-16: la pista principal no se apoya en el ramal ni en el relleno que parten de su superficie (un ciclo del grafo: ella los lee a ellos al recalcularse); la plataforma de la que parte, sí,
        y el ramal, en la pista (su origen está en su eje)."""
        records = chain()
        self.assertEqual(entities.unsupportable(records, "RDW-001"), frozenset({"RDW-001", "RDW-002", "PLT-002"}))
        self.assertNotIn("PLT-001", entities.unsupportable(records, "RDW-001"))
        self.assertNotIn("RDW-001", entities.unsupportable(records, "RDW-002"))
        self.assertEqual(entities.unsupportable(records, "RDW-002"), frozenset({"RDW-002", "PLT-002"}))


class FillOnTheRoadTest(unittest.TestCase):
    """RF-015-15, P-5, CE-017-08: un relleno posterior se apoya en la pista con su volumen, con **la superficie entera y la huella de una pista calculada**."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = ramp_job()
        cls.outcome = last(road_store.road_compute_steps(cls.job, COMMON))
        cls.road = cls.outcome.compose(cls.job.start)  # ``des_psf_``: la superficie entera
        (row,) = road_store.road_entity_rows(cls.job, cls.outcome, fid=1, start_surface="gis_dtm_rampa", support_surface=None)
        cls.footprint = json.loads(row[12])  # ``des_epr_``: la huella de la sección en tramos de fila
        cls.mask = entity_store.runs_mask(cls.footprint, GRID.shape)
        cls.terrain = np.asarray(cls.job.start, dtype=np.float64)

    def detect(self, result: np.ndarray, start: np.ndarray, thickness: float = 0.02) -> tuple[Any, ...]:
        return entities.detect_supports(result, start, {"RDW-001": self.road}, {"RDW-001": entities.runs_cells(self.footprint)}, thickness, GRID.cell_area)

    def by_hand(self, result: np.ndarray, start: np.ndarray, thickness: float = 0.02) -> tuple[int, float]:
        """La cuenta a mano, celda a celda (sin el código bajo prueba): las celdas de la huella con más del espesor sobre ``máx(partida, pista)`` y su volumen."""
        cells, volume = 0, 0.0
        for row, column in zip(*np.nonzero(self.mask), strict=True):
            above = result[row, column] - max(start[row, column], self.road[row, column])
            if above > thickness:
                cells += 1
                volume += above * GRID.cell_area
        return cells, volume

    def test_a_a_fill_over_the_carriageway_is_supported_on_the_road_with_its_volume(self) -> None:
        """RF-015-15, CE-017-08: un relleno posterior que parte de la superficie de la pista y la sube 0,5 m sobre toda su huella se apoya en ella con ``0,5 · celdas · 4 m²`` (a ≤ 10⁻⁹ relativo de la cuenta a
        mano); la pista es la entidad de apoyo (``RDW-001``) y sus celdas, las de la huella."""
        result = np.where(self.mask, self.road + 0.5, self.road)
        (found,) = self.detect(result, self.road)
        cells = int(self.mask.sum())
        self.assertEqual((found.code, found.cells, found.declared), ("RDW-001", cells, False))
        self.assertAlmostEqual(found.volume_m3, 0.5 * cells * GRID.cell_area, delta=TOL * found.volume_m3)
        self.assertEqual((found.cells, found.volume_m3), (cells, self.by_hand(result, self.road)[1]))

    def test_b_a_fill_from_the_terrain_counts_what_is_above_the_greater_of_the_terrain_and_the_road(self) -> None:
        """RF-015-15, P-5: un relleno que parte del **terreno** (a 120 m) y rellena sobre la pista cuenta lo que queda sobre ``máx(terreno, pista)``: la cuenta a mano de cada celda de la huella; con el
        espesor mínimo exacto (``120 − máx`` igual al espesor) la celda no cuenta (estricto)."""
        result = np.where(self.mask, 120.0, self.terrain)
        (found,) = self.detect(result, self.terrain)
        cells, volume = self.by_hand(result, self.terrain)
        self.assertGreater(cells, 0)
        self.assertEqual(found.cells, cells)
        self.assertAlmostEqual(found.volume_m3, volume, delta=TOL * volume)
        base = np.maximum(self.terrain, self.road)
        level = np.where(self.mask, base + 0.5, base)
        thick = (level - base)[self.mask]
        self.assertEqual(self.detect(level, base, thickness=float(thick.max())), (), "con el espesor mínimo exacto la celda no cuenta (estricto)")
        (every,) = self.detect(level, base, thickness=float(np.nextafter(thick.min(), 0.0)))
        self.assertEqual(every.cells, int(self.mask.sum()), "con el espesor mínimo apenas menor cuenta toda la huella")

    def test_c_what_only_drags_the_terrain_over_a_road_in_cut_does_not_count(self) -> None:
        """RF-015-15, P-5: un diseño posterior que **arrastra el terreno** (``resultado = partida``) sobre una pista que corta (``pista < terreno``) no apoya nada en ella: sin el ``máx`` contaría todo el desmonte."""
        self.assertLess(float(np.min((self.road - self.terrain)[self.mask])), -0.01, "la rampa corta el terreno en parte de su huella")
        self.assertEqual(self.detect(self.terrain, self.terrain), ())


class ReleaseBlockerTest(unittest.TestCase):
    """RF-015-17 (A7, P-6): lo que de una pista **es** la entidad descartada no se puede dar por bueno sin ella."""

    def test_a_the_origin_the_destination_and_the_support_surface_that_name_the_entity(self) -> None:
        """RF-017-03, RF-015-17: el origen en el eje de una pista (``RDW-001@100,5``), el destino en una entidad (``entity:PLT-001``) y la superficie de apoyo (``entity:RDW-001``) **son** de la entidad
        descartada: no se repite la pista sin ella (su geometría y su cota salen de ella); el primero que lo es, en el orden origen, destino y apoyo."""
        blocker = entity_store._release_blocker
        self.assertEqual(blocker({"origin": "RDW-001@100,5"}, "RDW-001"), params.RoadParam.ORIGIN)
        self.assertEqual(blocker({"origin": "Origen rampa", "destination": "entity:PLT-001"}, "PLT-001"), params.RoadParam.DESTINATION)
        self.assertEqual(blocker({"support": "entity:RDW-001"}, "RDW-001"), params.RoadParam.SUPPORT)
        self.assertEqual(blocker({"origin": "RDW-001@10", "destination": "entity:RDW-001", "support": "entity:RDW-001"}, "RDW-001"), params.RoadParam.ORIGIN)

    def test_b_what_is_not_a_reference_to_the_entity_does_not_block(self) -> None:
        """RF-015-17: un punto de la capa (su nombre), otra entidad, un valor que falta o lo que solo **declara** la persona (``supports``) no impide darla por buena: se repite sin esa entrada."""
        blocker = entity_store._release_blocker
        self.assertIsNone(blocker({"origin": "Origen rampa", "destination": "Destino rampa"}, "RDW-001"))
        self.assertIsNone(blocker({"origin": "RDW-002@100", "destination": "entity:PLT-001", "support": "entity:PLT-002"}, "RDW-001"))
        self.assertIsNone(blocker({}, "RDW-001"))
        self.assertIsNone(blocker({"supports": "RDW-001", "start": "entity:RDW-001"}, "RDW-001"), "lo declarado y la partida no son de este rechazo (la partida: ``des.entity_release_start``)")
        self.assertIsNone(blocker({"origin": None, "destination": ""}, "RDW-001"))

    def test_c_the_rejection_names_the_road_the_field_the_value_and_the_entity(self) -> None:
        """RF-015-17, RF-017-04 (como RF-015-08): ``des.road_release_geometry`` nombra la pista, el campo (la clave de su origen o su destino), el valor y la entidad descartada, dice que no se hace nada y qué
        hacer (rehacerla con otro punto o descartarla), en español y en inglés y sin marcadores sin llenar."""
        error = messages.DesignError("des.road_release_geometry", obj="Operación «Ramal»", field="des.road.rdw_002.origin", value="RDW-001@100", entity="Ramal", target="Pista a P1")
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
            self.assertIn("Pista a P1", text)
            self.assertIn("RDW-001@100", text)
            self.assertIn("des.road.rdw_002.origin", text)
        self.assertIn("no se hace nada", error.text)
        self.assertIn("nothing is done", error.text_in("en"))


class ReleasedRoadTest(unittest.TestCase):
    """RF-015-17, RF-008-26: ``recompute_road`` ya acepta lo que se da por bueno (era el ``NotImplementedError`` de la T22)."""

    def test_a_released_is_passed_on_and_no_longer_refused_as_not_done(self) -> None:
        """RF-015-17: con ``released`` la petición se trata como sin él: unos ajustes que no son los de una pista dan el mismo ``ValueError`` («code») y no el ``NotImplementedError`` de «es de la T24»; sin empezar
        nada (el proyecto de la petición es un objeto que no se toca)."""
        released = (provenance.ReleasedSupport("RDW-001", "Se elige otro trazado", "Samuel", "2026-11-21"),)
        road = core_recompute.RecomputeRequest(object(), "uid", provenance.ROAD, {}, (), ())
        for given in ((), released):
            with self.subTest(released=bool(given)), self.assertRaises(ValueError) as caught:
                road_store.recompute_road(road, released=given)
            self.assertIn("code", str(caught.exception))

    def test_b_what_rests_without_starting_from_the_discarded_road_can_be_given_as_good(self) -> None:
        """RF-015-17, RF-017-03, D-24: las listas del marco valen para la pista tal cual (sin regla nueva del grafo, P-5): lo que perdió su apoyo y **solo se apoyaba** en la pista descartada
        (``supported_on``: un relleno posterior, lo que declaró la persona) se puede dar por bueno; lo que **parte de su superficie** (``surface``: el ramal) se rehace sobre otra superficie o se
        descarta; la causa dice «se descartó la pista «…»» con su nombre."""
        def lost(*roles: str) -> Any:
            return entities.RetiredSupport("u", "Ramal", provenance.ROAD, "RDW-002", (entities.RetiredEntity("RDW-001", "Pista a P1", "d", "des_psf_pista_a_p1", roles),))

        self.assertEqual((lost("supported_on").releasable, lost("supported_on", "surface").releasable, lost("surface").releasable), (True, False, False))
        self.assertEqual(lost("supported_on", "surface").text("es"), "Apoyo retirado: se descartó la pista «Pista a P1»")
        self.assertEqual(lost("supported_on").text("en"), "Support removed: the haul road «Pista a P1» was discarded")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
