# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que se apoyaba en el acopio que se retira y «apoyo retirado» (spec 016, T18; HU-016-2; RF-016-14, RF-015-15, RF-015-17;
CE-016-04; plan 016 §5.4 A7 y A13, §5.7 P-9; ADR-0031 §4; error 59). El cálculo puro, en el «verde»; con proyecto, en el paso
«hito» (``milestone_removal_resting.py``: la rejilla de 2 m, P-13).

**A7** (:func:`design.removal.attribute_resting`): hacia atrás por la cadena de superficies desde la de partida, cada
operación ``i`` que dejó ``S_i`` desde ``S_{i−1}`` recibe ``Σ máx(S_i, T) − máx(S_{i−1}, T)`` en las celdas de la huella del
acopio donde sube **más** del espesor mínimo de la 012 (``T``, la superficie con que se detectó); la raíz de la cadena, si no es
la superficie de la detección (una superficie de otra versión), recibe lo suyo por encima de ``T``. Se prueba con **cuentas a mano**,
una implementación independiente (un bucle por celda con ``math.fsum``) y las propiedades de la suma (telescopa: lo apoyado en
total es lo que la partida tiene por encima de ``T``), el umbral exclusivo al último bit, lo que se baja (no cuenta), las celdas
sin dato y los rechazos del programa.

**La lista y la confirmación** (:class:`design.removal.Resting`, :func:`resting_notices`, :func:`check_resting_confirmed`): una
sola lista con nombre, tipo y volumen, el aviso ``des.removal_resting`` con su total y sus nombres y la negativa a retirarlo sin
la confirmación expresa (``des.removal_resting_unconfirmed``), en los dos idiomas.

**«Apoyo retirado» por una retirada viva** (:func:`design.entities._retired_by`, P-9): lo que se apoyaba en **un acopio** que
retira una retirada viva, y solo lo que está en la cadena de su partida (aguas arriba), pierde su apoyo; el texto de su causa nombra
el acopio y la retirada, y la operación que se apoya en otro acopio no.

**Lo que la retirada anota** (T45; hallazgos S-1 y B-1; :func:`design.removal.resting_record`, :func:`design.entities._retired_by_rows`): además de las
cifras del relleno, «apoyo retirado» lee de los ajustes de la retirada la lista de lo que se le apoyaba al crearla (la que se listó y se confirmó): vale con
la detección del proyecto y con el relleno hecho antes que la detección, que no tienen cifra.
"""

from __future__ import annotations

import json
import math
import random
import unittest

import numpy as np

from tests.support.package import import_geoblender

entities = import_geoblender("design.entities")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
removal = import_geoblender("design.removal")

DesignError = messages.DesignError
E = 0.02
"""El espesor mínimo de la 012 por defecto (m)."""
AREA = 4.0
"""El área de una celda de 2 m (m²)."""
FOUR, THREE = "Acopio 4", "Acopio 3"


def by_hand(floor: list[float], levels: list[list[float]], thickness: float = E, area: float = AREA
            ) -> list[tuple[int, float]]:
    """A7 en un bucle de Python, sin el código que se prueba: de cada nivel, las celdas donde ``máx(S_k, T) − máx(S_{k−1}, T)`` pasa de
    ``thickness`` (la raíz se compara con ``T``) y la suma de lo que sube (``fsum``) por el área de una celda."""
    found: list[tuple[int, float]] = []
    before = list(floor)
    for level in levels:
        gained: list[float] = []
        for index, (now, T) in enumerate(zip(level, floor, strict=True)):
            if math.isnan(now) or math.isnan(before[index]) or math.isnan(T):
                continue
            rise = max(now, T) - max(before[index], T)
            if rise > thickness:
                gained.append(rise)
        found.append((len(gained), math.fsum(gained) * area))
        before = [max(now, T) if not math.isnan(now) else math.nan for now, T in zip(level, floor, strict=True)]
    return found


def run(floor: list[float], levels: list[list[float]], thickness: float = E, area: float = AREA) -> list[tuple[int, float]]:
    """:func:`~design.removal.attribute_resting` con listas, como pares ``(celdas, m³)``."""
    shares = removal.attribute_resting(np.array(floor), [np.array(level) for level in levels], thickness, area)
    return [(share.cells, share.volume_m3) for share in shares]


class AttributeRestingTest(unittest.TestCase):
    def test_a_chain_of_two_fills_by_hand(self) -> None:
        """RF-016-14 (A7): la cadena detección → «Relleno 1» (sube 3 m en 4 celdas, 1 cm en una —no pasa del espesor mínimo— y una
        sin dato) → «Relleno 2» (sube 2 m en una celda del primero y 5 en otra, y **baja** 1 m en otra, que no cuenta): cada
        operación recibe lo suyo, a mano."""
        floor = [100.0] * 6
        survey = [100.0] * 6
        first = [103.0, 103.0, 103.0, 103.0, 100.01, math.nan]
        second = [105.0, 103.0, 103.0, 102.0, 105.0, 104.0]
        found = run(floor, [survey, first, second])
        # raíz: es la superficie de la detección → nada; Relleno 1: 4 celdas · 3 m · 4 m²; Relleno 2: 5 − 3 = 2 m en la celda 0 y
        # 105 − 100,01 → 4,99 m en la celda 4 (la 4 del primero estaba en 100,01) y 104 − 100 (la 5 no tenía dato antes: no cuenta).
        self.assertEqual(found[0], (0, 0.0))
        self.assertEqual(found[1], (4, 4 * 3.0 * AREA))
        self.assertEqual(found[2][0], 2)
        self.assertEqual(found[2][1], (2.0 + (105.0 - 100.01)) * AREA)
        self.assertEqual(found, by_hand(floor, [survey, first, second]))

    def test_the_total_is_what_the_start_surface_has_above_the_detection_surface(self) -> None:
        """RF-016-14 (A7): la suma de lo atribuido **telescopa**: con cada subida por encima del espesor mínimo, lo apoyado en total
        es ``Σ máx(partida, T) − T`` en la huella (cuando todo lo que se rellena cuenta), con cualquier número de operaciones y datos
        al azar (a ≤ 10⁻⁹ relativo), y cada una coincide con el bucle independiente."""
        rng = random.Random(20261119)
        for _ in range(40):
            cells = rng.randint(5, 60)
            floor = [rng.uniform(90.0, 110.0) for _ in range(cells)]
            level = list(floor)
            levels = [list(floor)]
            for _step in range(rng.randint(1, 5)):
                level = [value + rng.uniform(0.5, 4.0) * (rng.random() < 0.7) for value in level]
                levels.append(list(level))
            found = run(floor, levels)
            self.assertEqual(found, by_hand(floor, levels))
            total = math.fsum(volume for _cells, volume in found)
            wanted = math.fsum(max(now, T) - T for now, T in zip(level, floor, strict=True)) * AREA
            if wanted:
                self.assertLessEqual(abs(total - wanted) / wanted, 1e-9)

    def test_the_minimum_thickness_is_exclusive_to_the_last_bit(self) -> None:
        """RF-016-14, RF-015-15: sube **más** del espesor mínimo: una subida de exactamente ``e`` no cuenta y una del siguiente
        número representable, sí (el mismo criterio que ``detect_supports``)."""
        floor = [0.0, 0.0]
        just_above = float(np.nextafter(E, 1.0))
        self.assertGreater(just_above, E)
        found = run(floor, [[0.0, 0.0], [E, just_above]])
        self.assertEqual(found[1], (1, just_above * AREA))
        self.assertEqual(found, by_hand(floor, [[0.0, 0.0], [E, just_above]]))
        self.assertEqual(run(floor, [[0.0, 0.0], [E, E]])[1], (0, 0.0))
        self.assertEqual(run(floor, [[0.0, 0.0], [1.0, 1.0]], thickness=0.0)[1], (2, 2.0 * AREA))

    def test_what_is_lowered_or_cut_does_not_count_and_what_is_filled_after_a_cut_does(self) -> None:
        """RF-016-14 (A7): una operación que **baja** la superficie no recibe nada (la subida no es negativa), y la que rellena
        después de un corte que dejó la superficie por debajo de ``T`` recibe todo lo que pone por encima de ``T``: ``máx(S, T)``
        mide siempre sobre el acopio."""
        floor = [100.0, 100.0, 100.0]
        survey = [104.0, 104.0, 104.0]  # el montón sigue en la partida: lo que está por encima de T lo puso quien hizo la raíz
        found = run(floor, [survey, [102.0, 99.0, 104.0], [103.5, 103.5, 104.0]])
        self.assertEqual(found[0], (3, 3 * 4.0 * AREA), "la raíz con 4 m por encima de T: de la superficie por su nombre")
        self.assertEqual(found[1], (0, 0.0), "una operación que solo baja o deja igual no recibe nada")
        self.assertEqual(found[2], (2, ((103.5 - 102.0) + (103.5 - 100.0)) * AREA))
        self.assertEqual(found, by_hand(floor, [survey, [102.0, 99.0, 104.0], [103.5, 103.5, 104.0]]))

    def test_a_cell_without_data_never_counts(self) -> None:
        """RF-016-14: una celda sin dato (``NaN``) en cualquiera de las superficies no cuenta, ni como apoyada ni como cero."""
        floor = [100.0, 100.0, 100.0, math.nan]
        found = run(floor, [[100.0, math.nan, 100.0, 100.0], [101.0, 102.0, math.nan, 102.0]])
        self.assertEqual(found[0], (0, 0.0))
        self.assertEqual(found[1], (1, 1.0 * AREA), "solo la celda 0 tiene dato en las tres")

    def test_the_root_that_is_not_the_detection_surface_gets_what_it_has_above_it(self) -> None:
        """RF-016-14: si la cadena no llega a la superficie de la detección (la de partida viene de otra versión), su raíz
        recibe todo lo que tiene por encima de ``T``, por su nombre: una sola fila con el volumen a mano."""
        floor = [100.0] * 4
        start = [102.0, 103.0, 100.0, 100.01]
        found = run(floor, [start])
        self.assertEqual(found, [(2, (2.0 + 3.0) * AREA)])
        self.assertEqual(found, by_hand(floor, [start]))

    def test_the_inputs_are_not_modified(self) -> None:
        """RNF-016-02: ninguna entrada se modifica."""
        floor, level = np.array([100.0, 100.0]), np.array([103.0, math.nan])
        before = (floor.copy(), level.copy())
        removal.attribute_resting(floor, [level], E, AREA)
        np.testing.assert_array_equal(floor, before[0])
        np.testing.assert_array_equal(level, before[1])

    def test_program_errors(self) -> None:
        """Errores del programa (``ValueError``): niveles de otra forma que ``T``, un espesor negativo o no finito y un área que
        no es positiva; sin niveles, nada."""
        floor = np.array([100.0, 100.0])
        for level in (np.array([100.0]), np.array([[100.0, 100.0]])):
            with self.subTest(level=level.shape), self.assertRaises(ValueError):
                removal.attribute_resting(floor, [level], E, AREA)
        for thickness in (-0.01, math.nan, math.inf):
            with self.subTest(thickness=thickness), self.assertRaises(ValueError):
                removal.attribute_resting(floor, [floor], thickness, AREA)
        for area in (0.0, -4.0, math.nan):
            with self.subTest(area=area), self.assertRaises(ValueError):
                removal.attribute_resting(floor, [floor], E, area)
        self.assertEqual(removal.attribute_resting(floor, [], E, AREA), ())


def rows() -> list:
    """Dos filas de la lista: un relleno de la 015 y la superficie de partida de otra versión."""
    return [removal.Resting("Sobre el acopio 4", "des.platform", 2590.2, 648, "des_psf_sobre_el_acopio_4",
                            operation_uid="op-1", entity="PLT-001"),
            removal.Resting("des_psf_de_v01", None, 120.4, 30, "des_psf_de_v01")]


class RestingListTest(unittest.TestCase):
    def test_a_row_reads_with_its_name_kind_and_volume_in_both_languages(self) -> None:
        """RF-016-14, RF-015-17: una fila de la lista dice el nombre, el tipo y los m³ de lo apoyado, en español y en inglés, sin
        ningún marcador sin llenar; la de una superficie (sin operación) dice que es la de partida."""
        entity, surface = rows()
        self.assertTrue(entity.text("es").startswith("Sobre el acopio 4 (Plataforma): "), entity.text("es"))
        self.assertTrue(entity.text("es").endswith(" m³ apoyados"), entity.text("es"))
        for item in (entity, surface):
            for language in ("es", "en"):
                with self.subTest(name=item.name, language=language):
                    text = item.text(language)
                    self.assertNotIn("{", text)
                    self.assertNotIn("?", text)
                    self.assertIn(item.name, text)
        self.assertIn("m³", entity.text("es"))
        self.assertIn("superficie de partida", surface.text("es"))
        self.assertIn("start surface", surface.text("en"))
        self.assertEqual(entity.kind("es"), "Plataforma")
        self.assertIsNone(surface.kind("es"))

    def test_the_notice_gives_the_total_and_the_names_of_what_rests_on_the_stockpile(self) -> None:
        """RF-016-14: **una** nota (``des.removal_resting``) con el acopio, el total de m³ y los nombres de todo lo que se le apoya
        —también la superficie de otra versión, por su nombre—; sin nada apoyado, ninguna."""
        found = removal.resting_notices(FOUR, rows())
        self.assertEqual(len(found), 1)
        notice = found[0]
        self.assertEqual(notice.code, "des.removal_resting")
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(notice.values["stockpile"], FOUR)
        self.assertEqual(notice.values["volume"], 2590.2 + 120.4)
        text = notice.text("es")
        for wanted in (FOUR, "Sobre el acopio 4", "des_psf_de_v01", "confirmación expresa"):
            self.assertIn(wanted, text)
        self.assertNotIn("{", text)
        self.assertEqual(removal.resting_notices(FOUR, []), ())

    def test_a_long_list_names_the_first_ones_and_ends_with_an_ellipsis(self) -> None:
        """RF-016-14: con más de ``SUMMARY_ITEMS`` filas, el aviso nombra las primeras y acaba en «…»; el total las suma todas."""
        many = [removal.Resting(f"Relleno {number}", "des.fill_only", 10.0, 3, f"des_srf_r{number}") for number in range(1, 13)]
        (notice,) = removal.resting_notices(THREE, many)
        self.assertEqual(notice.values["volume"], 120.0)
        text = notice.text("es")
        self.assertIn("Relleno 1", text)
        self.assertIn("…", text)
        self.assertNotIn("Relleno 12", text)

    def test_what_rests_on_the_stockpile_is_not_removed_without_the_express_confirmation(self) -> None:
        """RF-016-14, RF-015-17 (error 59): con algo apoyado y sin confirmación, ``des.removal_resting_unconfirmed`` con el acopio y el
        total, en los dos idiomas y sin marcadores sin llenar; con confirmación, o sin nada apoyado, no pasa nada."""
        with self.assertRaises(DesignError) as caught:
            removal.check_resting_confirmed(FOUR, rows(), confirmed=False)
        error = caught.exception
        self.assertEqual(error.code, "des.removal_resting_unconfirmed")
        self.assertEqual(error.values["stockpile"], FOUR)
        self.assertEqual(error.values["volume"], 2590.2 + 120.4)
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertIn(FOUR, text)
        self.assertIsNone(removal.check_resting_confirmed(FOUR, rows(), confirmed=True))
        self.assertIsNone(removal.check_resting_confirmed(FOUR, [], confirmed=False))


class StockpileRemovedTextTest(unittest.TestCase):
    def test_the_cause_names_the_stockpile_and_the_removal(self) -> None:
        """RF-015-17, P-9: la causa de «apoyo retirado» por una retirada viva nombra el acopio y la retirada, en los dos idiomas
        (``Apoyo retirado: se retiró el acopio «Acopio 4» (retirada «Retirada 1»)»)."""
        lost = entities.RetiredEntity("STK-001", "Acopios", "ds-1", "des_stp_acopios", ("supported_on",),
                                      removal="Retirada 1", stockpile=FOUR)
        item = entities.RetiredSupport("op-1", "Sobre el acopio 4", "des.platform", "PLT-001", (lost,))
        es, en = item.text("es"), item.text("en")
        self.assertTrue(es.startswith("Apoyo retirado: "), es)
        for wanted in (FOUR, "Retirada 1", "retir"):
            self.assertIn(wanted, es)
        self.assertTrue(en.startswith("Support removed: "), en)
        self.assertIn("Retirada 1", en)
        self.assertNotIn("{", es + en)
        self.assertTrue(item.releasable, "se puede dar por buena (no parte de su superficie)")

    def test_a_discarded_entity_keeps_its_old_text(self) -> None:
        """RF-015-17 sin cambios: lo descartado (sin retirada) dice «se descartó…» como antes."""
        lost = entities.RetiredEntity("PLT-001", "P1", "ds-1", "des_psf_p1", ("supported_on",))
        text = entities.RetiredSupport("op-2", "P2", "des.platform", "PLT-002", (lost,)).text("es")
        self.assertEqual(text, "Apoyo retirado: se descartó «P1»")


def removal_ref(code: str = "STK-001", key: str = FOUR, name: str = "Retirada 1", uid: str = "rm-1", resting: tuple[str, ...] = ()) -> object:
    """Una retirada viva de la que solo importa lo que decide quién pierde el apoyo: su operación, su nombre y el acopio y, si la anotó
    (T45), lo que se le apoyaba al crearla (``resting``: los uid de las operaciones)."""
    return entities.StockpileRemoval(uid, name, "RMV-001", f"{code}#{key}", code, key, resting=resting)


class RetiredByTest(unittest.TestCase):
    """P-9 (la decisión pura): quién pierde su apoyo por una retirada viva."""

    def test_only_what_rests_on_the_stockpile_that_is_removed_and_is_upstream_of_the_removal_loses_its_support(self) -> None:
        """RF-016-14, RF-015-17, P-9 (CE-016-04): una operación que se apoya en el acopio que retira una retirada viva **y** está
        en la cadena de su partida pierde el apoyo; la que se apoya en **otro** acopio de la misma detección, no; tampoco la que
        está aguas abajo de la retirada (no está en la cadena de su partida): solo quedará obsoleta si cambia."""
        removals = [removal_ref()]
        supported = {"op-four": {f"STK-001#{FOUR}"}, "op-three": {f"STK-001#{THREE}"}, "op-after": {f"STK-001#{FOUR}"},
                     "op-both": {f"STK-001#{THREE}", f"STK-001#{FOUR}"}}
        upstream = {"rm-1": {"op-four", "op-three", "op-both"}}
        found = entities._retired_by(removals, supported, upstream)
        self.assertEqual(sorted(found), ["op-both", "op-four"])
        self.assertEqual([item.removal for item in found["op-four"]], ["Retirada 1"])
        self.assertEqual([item.stockpile for item in found["op-four"]], [f"STK-001#{FOUR}"])
        self.assertEqual(found["op-both"][0].key, FOUR, "solo el acopio que retira, no el otro en el que también se apoya")

    def test_two_removals_of_two_stockpiles_retire_what_rested_on_each(self) -> None:
        """RF-016-14, P-9: dos retiradas vivas (dos acopios de la misma detección): cada operación pierde el apoyo de la que
        retira **su** acopio, con las dos si se apoyaba en los dos."""
        removals = [removal_ref(uid="rm-1"), removal_ref(key=THREE, name="Retirada 2", uid="rm-2")]
        supported = {"op-four": {f"STK-001#{FOUR}"}, "op-three": {f"STK-001#{THREE}"},
                     "op-both": {f"STK-001#{THREE}", f"STK-001#{FOUR}"}}
        upstream = {"rm-1": {"op-four", "op-three", "op-both"}, "rm-2": {"op-three", "op-both"}}
        found = entities._retired_by(removals, supported, upstream)
        self.assertEqual({uid: [item.removal for item in items] for uid, items in found.items()},
                         {"op-four": ["Retirada 1"], "op-three": ["Retirada 2"], "op-both": ["Retirada 1", "Retirada 2"]})

    def test_nothing_is_retired_without_a_live_removal_or_when_it_rested_on_something_else(self) -> None:
        """RF-015-17 sin cambios: sin retiradas vivas, nadie pierde nada (ni se hace ninguna consulta de más); una operación que
        se apoya en una **entidad** (no en un acopio) tampoco, aunque la detección se retire."""
        supported = {"op-four": {f"STK-001#{FOUR}"}, "op-plt": {"PLT-001"}}
        self.assertEqual(entities._retired_by([], supported, {}), {})
        self.assertEqual(entities._retired_by([removal_ref()], {"op-plt": {"PLT-001"}}, {"rm-1": {"op-plt"}}), {})
        self.assertEqual(entities._retired_by([removal_ref(code="STK-002")], supported, {"rm-1": {"op-four"}}), {},
                         "otra detección")


class RestingRecordTest(unittest.TestCase):
    """T45 (RF-016-14, RF-015-17; hallazgos S-1 y B-1): lo que la retirada **anota** de la lista de lo que se le apoyaba, que es lo que lee P-9."""

    def rows(self) -> list[object]:
        return [removal.Resting("Sobre el acopio 4", "des.platform", 2590.25, 40, "des_psf_sobre_el_acopio_4", "uid-plt", "PLT-001"),
                removal.Resting("Tercera", "des.fill_only", 12.5, 3, "des_psf_tercera", "uid-fill", None),
                removal.Resting("des_psf_de_otra_version", None, 99.0, 7, "des_psf_de_otra_version")]

    def test_the_record_keeps_what_an_operation_put_and_leaves_out_the_surface_of_another_version(self) -> None:
        """RF-016-14, P-9: se anota una fila por **operación** de la versión (entidad o diseño de la 013 y la 014) con su uid, su nombre, su
        código si es una entidad, su volumen y sus celdas; la superficie de otra versión (sin operación) no: no hay nadie a quien quitarle el
        apoyo. Es un JSON de los ajustes de la operación (finito, sin objetos del programa)."""
        found = removal.resting_record(self.rows())
        self.assertEqual(found, [
            {"operation": "uid-plt", "name": "Sobre el acopio 4", "entity": "PLT-001", "volume_m3": 2590.25, "cells": 40},
            {"operation": "uid-fill", "name": "Tercera", "entity": None, "volume_m3": 12.5, "cells": 3}])
        self.assertEqual(json.loads(json.dumps(found, allow_nan=False)), found)
        self.assertEqual(removal.resting_record([]), [])

    def test_the_operations_come_back_from_the_settings_and_a_broken_record_is_nothing(self) -> None:
        """RF-016-14, P-9: ``entities._resting_ops`` lee del ajuste los uid de las operaciones, en su orden; sin el ajuste (una retirada de
        antes de la T45, o hecha a mano), o con algo que no es una lista de filas con su operación, ninguna: **nunca lanza** (el registro
        de las entidades lo lee toda vez)."""
        record = removal.resting_record(self.rows())
        settings = {"name": "R", "code": "RMV-001", provenance.REMOVAL_RESTING: record}
        self.assertEqual(entities._resting_ops(settings), ("uid-plt", "uid-fill"))
        self.assertEqual(entities._resting_ops({"name": "R"}), ())
        for broken in (None, "uid-plt", 3, {"operation": "x"}, [None, 4, "x", {"name": "sin operación"}, {"operation": 5}, {"operation": ""}]):
            with self.subTest(broken=broken):
                self.assertEqual(entities._resting_ops({provenance.REMOVAL_RESTING: broken}), ())
        self.assertEqual(entities._resting_ops({provenance.REMOVAL_RESTING: [{"operation": "a"}, {"operation": "a"}, {"operation": "b"}]}),
                         ("a", "b"), "sin repetir")


class RetiredByRowsTest(unittest.TestCase):
    """T45, P-9 (la decisión pura de lo que la retirada anotó): quién pierde el apoyo **por lo que se le listó y se confirmó**, sin cifras del
    relleno (la detección del proyecto, o el relleno hecho antes que la detección)."""

    def test_what_the_removal_listed_and_is_still_current_loses_its_support(self) -> None:
        """RF-016-14, RF-015-17, P-9 (CE-016-04; S-1): la operación que la retirada anotó como apoyada en el acopio y sigue vigente pierde su
        apoyo, con la retirada; la que no anotó, no (lo que va después de la retirada en la cadena no está en su lista)."""
        removals = [removal_ref(resting=("op-four", "op-gone"))]
        found = entities._retired_by_rows(removals, {"op-four": frozenset(), "op-after": frozenset()})
        self.assertEqual(sorted(found), ["op-four"])
        self.assertEqual([(item.removal, item.key, item.operation) for item in found["op-four"]], [("Retirada 1", FOUR, "rm-1")])

    def test_what_was_listed_but_is_no_longer_the_current_operation_is_not_retired(self) -> None:
        """RF-015-17, P-9: la operación anotada que ya no es la vigente (la sustituyó otra, o no se hizo) no pierde nada: la lista de la
        retirada se rehace al recalcularla; solo cuenta la que hoy hay."""
        self.assertEqual(entities._retired_by_rows([removal_ref(resting=("op-old",))], {}), {})

    def test_what_gave_that_detection_as_good_is_not_retired_again(self) -> None:
        """RF-015-17, P-9 (T25 de la 015; «dar por buena»): la operación vigente que **dio por bueno sin su apoyo** el de esa detección no vuelve
        a perderlo al recalcular la retirada (que la volverá a listar): su decisión manda; la que dio por bueno otra detección, sí lo pierde."""
        removals = [removal_ref(resting=("op-a", "op-b"))]
        found = entities._retired_by_rows(removals, {"op-a": frozenset({"STK-001"}), "op-b": frozenset({"STK-002"})})
        self.assertEqual(sorted(found), ["op-b"])

    def test_two_removals_retire_what_each_listed_without_repeating_a_removal(self) -> None:
        """RF-016-14, P-9: dos retiradas vivas anotan cada una lo suyo; una operación en las dos las tiene a las dos, en el orden de las
        retiradas, y una retirada que repite la operación en su lista la cuenta una vez."""
        removals = [removal_ref(uid="rm-1", resting=("op-a", "op-a")),
                    removal_ref(key=THREE, name="Retirada 2", uid="rm-2", resting=("op-a", "op-b"))]
        found = entities._retired_by_rows(removals, {"op-a": frozenset(), "op-b": frozenset()})
        self.assertEqual({uid: [item.removal for item in items] for uid, items in found.items()},
                         {"op-a": ["Retirada 1", "Retirada 2"], "op-b": ["Retirada 2"]})

    def test_a_removal_that_listed_nothing_retires_nothing(self) -> None:
        """RF-015-17: sin lista (la retirada no tenía nada apoyado, o es anterior a la T45) no hay nada que quitar por este camino."""
        self.assertEqual(entities._retired_by_rows([removal_ref()], {"op-a": frozenset()}), {})
        self.assertEqual(entities._retired_by_rows([], {"op-a": frozenset()}), {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
