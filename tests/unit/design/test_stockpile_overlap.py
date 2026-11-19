# SPDX-License-Identifier: GPL-3.0-or-later
"""Dos marcas solapadas rechazan **solo esas dos marcas** (spec 016, T48; hallazgos A-2 y S-3 de la verificación única; RF-016-04,
RF-016-06, RF-016-08; plan 016 §5.2.1).

RF-016-04: «SI la marca se solapa con otra, ENTONCES rechazar ese acopio nombrando la marca (o las dos), el caso y su lugar, y NO
registrarlo». La T11 rechazaba **toda la detección** con la primera pareja (``des.stockpile_marks_overlap``, un error): con 100 marcas un
solape bloqueaba 98 y «Recalcular lo obsoleto» no repetía nada. Ahora la preparación aparta las marcas que se solapan
(:func:`design.stockpiles.refuse_overlaps`: ``RefusedMark``, con el aviso de la pareja) y el cálculo las informa como las demás marcas
rechazadas, sin registrarlas y sin que su montículo vuelva como candidato; las otras siguen.

Sobre la ventana de 120 m con celdas de 1 m de los dos acopios que se tocan (``tests.support.stockpile_data.touching_pair``) y un tercer
montículo, con las cuentas a mano.
"""

from __future__ import annotations

import unittest

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design.test_stockpile_candidates import cparams
from tests.unit.design.test_stockpile_footprint import params_of

messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
stockpile_store = import_geoblender("design.stockpile_store")
stockpiles = import_geoblender("design.stockpiles")

OVERLAP = "des.stockpile_marks_overlap"
THIRD = sdata.Mound("C", "pyramid", 100.0, 100.0, 10.0, 4.0, 4.0)
"""Un tercer montículo (a 30 m del segundo del caso de los dos acopios) con su marca."""
A_BOX, B_BOX, C_BOX = (40.0, 50.0, 64.0, 70.0), (60.0, 50.0, 80.0, 70.0), (90.0, 90.0, 110.0, 110.0)
"""Las marcas A y B se solapan en x de 60 a 64 m y en y de 50 a 70 m (4 × 20 celdas de 1 m: 80 m²); C está lejos."""


def mark_of(name: str, box: tuple[float, float, float, float], grid: object) -> object:
    return stockpiles.StockpileMark(name, np.flatnonzero(sdata.in_box(box, grid)))


class Scene:
    """La ventana de los dos acopios que se tocan con el tercero."""

    def __init__(self) -> None:
        case = sdata.touching_pair()
        self.grid = case.grid
        self.terrain = case.terrain + sdata.mound_heights(case.grid.shape, case.grid.dx, (THIRD,))
        self.a, self.b, self.c = (mark_of(name, box, self.grid) for name, box in (("A", A_BOX), ("B", B_BOX), ("C", C_BOX)))

    def job(self, marks: tuple[object, ...], *, candidates: bool = False, refuse: bool = True) -> object:
        """El trabajo con ``marks``; con ``refuse``, las que se solapan apartadas como lo hace la preparación."""
        kept, refused = stockpiles.refuse_overlaps(marks, self.grid) if refuse else (marks, ())
        everything = sdata.in_box((0.0, 0.0, 120.0, 120.0), self.grid)
        return stockpiles.StockpileJob("Acopios", "STK-001", self.grid, self.terrain, kept, params_of(), None,
                                       cparams() if candidates else None, everything if candidates else None, refused)


class OverlapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scene = Scene()

    def test_a_two_overlapping_marks_are_refused_and_the_valid_one_is_detected(self) -> None:
        """RF-016-04: A y B solapadas y C válida: **C se detecta**; A y B se rechazan **por su nombre** con el caso (las dos marcas, el
        área común —4 columnas × 20 filas × 1 m² = 80 m²— y su lugar: el centro de las celdas comunes, x = 62 m, y = 60 m locales), sin
        registrarlas; el trabajo no se rechaza entero y la marca que no se solapa sale tal cual."""
        scene = self.scene
        kept, refused = stockpiles.refuse_overlaps((scene.a, scene.b, scene.c), scene.grid)
        self.assertEqual([mark.key for mark in kept], ["C"])
        self.assertIs(kept[0], scene.c)
        self.assertEqual([item.mark.key for item in refused], ["A", "B"])
        notice = refused[0].notice
        self.assertEqual(notice.code, OVERLAP)
        self.assertIs(refused[1].notice, notice, "la pareja es un solo aviso, el mismo en las dos")
        self.assertEqual((notice.values["mark"], notice.values["other"], notice.values["area"]), ("A", "B", 80.0))
        self.assertEqual((notice.values["x"], notice.values["y"]), (sdata.BASE[0] + 62.0, sdata.BASE[1] + 60.0))
        outcome = stockpiles.detect_stockpiles(scene.job((scene.a, scene.b, scene.c)))
        self.assertEqual([item.key for item in outcome.stockpiles], ["C"])
        self.assertEqual([item.key for item in outcome.rejected], ["A", "B"])
        self.assertEqual(outcome.rejected[0].notice.code, OVERLAP)
        overlap = [item for item in outcome.notices if item.code == OVERLAP]
        self.assertEqual(len(overlap), 1, "la pareja se cuenta una vez en los avisos")
        self.assertIn("2 marcas rechazadas", outcome.message)

    def test_b_the_refused_marks_name_both_in_the_summary_in_both_languages_and_are_not_registered(self) -> None:
        """RF-016-04: el resumen lista las dos marcas rechazadas (cada una con su clave y el aviso de la pareja, una sola línea de aviso)
        y el texto, en español y en inglés, nombra las dos, el área y que no se registran; la cifra de marcas rechazadas es 2 y las filas
        de ``des_stk_`` solo son las del acopio que sí se detecta."""
        scene = self.scene
        outcome = stockpiles.detect_stockpiles(scene.job((scene.a, scene.b, scene.c)))
        summary = stockpile_store.stockpile_summary(outcome, version="V01", scope=stockpile_store.VERSION)
        self.assertEqual([line.key for line in summary.rejected], ["A", "B"])
        lines = [notice for notice in summary.notices if notice.code == OVERLAP]
        self.assertEqual(len(lines), 1)
        for language, parts in (("es", ("«A»", "«B»", "80", "no se registra")), ("en", ("«A»", "«B»", "80", "neither stockpile is registered"))):
            text = lines[0].text(language)
            for part in parts:
                self.assertIn(part, text, language)
            self.assertNotIn("{", text)
        self.assertEqual(lines[0].severity, "warning", "es un aviso, no un error: la detección sigue")
        report = {row[0]: row[1] for row in stockpile_store.detection_report_rows(outcome) if row[0] == "rejected_marks"}
        self.assertEqual(report, {"rejected_marks": 2.0})
        rows = stockpile_store.stockpile_rows_of(scene.job((scene.a, scene.b, scene.c)), "marcas", {"A": 1, "B": 2, "C": 3}, outcome)
        self.assertEqual([row[1] for row in rows], ["C"])

    def test_c_the_mound_of_a_refused_mark_does_not_come_back_as_a_candidate(self) -> None:
        """RF-016-04, RF-016-08: pidiendo también los candidatos, el montículo de una marca rechazada por solape **no vuelve como
        candidato** (el montículo está en el terreno, no tiene marca válida: sus celdas cuentan como celdas con marca); sin apartar esas
        marcas del trabajo (A y B como si no existieran) sí saldría: la prueba lo muestra."""
        scene = self.scene
        outcome = stockpiles.detect_stockpiles(scene.job((scene.a, scene.b, scene.c), candidates=True))
        self.assertEqual(len(outcome.candidates.items), 0, [item.centre for item in outcome.candidates.items])
        self.assertGreaterEqual(outcome.candidates.on_marks, 1)
        without = stockpiles.detect_stockpiles(scene.job((scene.c,), candidates=True))
        centres = [item.centre for item in without.candidates.items]
        self.assertTrue(centres, "sin las marcas A y B su montículo sí sería candidato")
        for x, y in centres:
            self.assertTrue(40.0 + sdata.BASE[0] < x < 80.0 + sdata.BASE[0] and 50.0 + sdata.BASE[1] < y < 70.0 + sdata.BASE[1])

    def test_d_a_chain_a_b_c_refuses_the_three_and_a_valid_far_one_stays(self) -> None:
        """RF-016-04: con A–B y B–C solapadas (cada pareja, 2 columnas), las **tres** se rechazan, cada una con el aviso de su primera
        pareja (A y B, la pareja A–B; C, la B–C), en el orden de la capa y sin repetir un aviso; la cuarta, lejos, se queda."""
        grid = self.scene.grid
        marks = [mark_of(name, box, grid) for name, box in (("A", (10.0, 10.0, 30.0, 30.0)), ("B", (28.0, 10.0, 50.0, 30.0)),
                                                              ("C", (48.0, 10.0, 70.0, 30.0)), ("D", (90.0, 90.0, 110.0, 110.0)))]
        kept, refused = stockpiles.refuse_overlaps(marks, grid)
        self.assertEqual([mark.key for mark in kept], ["D"])
        self.assertEqual([item.mark.key for item in refused], ["A", "B", "C"])
        pairs = [(item.notice.values["mark"], item.notice.values["other"]) for item in refused]
        self.assertEqual(pairs, [("A", "B"), ("A", "B"), ("B", "C")])
        self.assertIs(refused[0].notice, refused[1].notice)
        self.assertEqual(refused[0].notice.values["area"], 40.0, "2 columnas × 20 filas × 1 m²")
        self.assertEqual(len({id(item.notice) for item in refused}), 2)

    def test_e_marks_that_do_not_overlap_are_untouched_and_only_touching_ones_pass(self) -> None:
        """RF-016-04, RF-016-06: sin solape (también las que solo se tocan por el borde: x = 60 m), ninguna se aparta y se devuelven los
        mismos objetos; con una sola marca o ninguna, nada que comprobar."""
        scene = self.scene
        touching = mark_of("T", (60.0, 50.0, 80.0, 70.0), scene.grid)
        left = mark_of("L", (40.0, 50.0, 60.0, 70.0), scene.grid)
        kept, refused = stockpiles.refuse_overlaps((left, touching, scene.c), scene.grid)
        self.assertEqual((kept, refused), ((left, touching, scene.c), ()))
        self.assertEqual(stockpiles.refuse_overlaps((scene.a,), scene.grid), ((scene.a,), ()))
        self.assertEqual(stockpiles.refuse_overlaps((), scene.grid), ((), ()))

    def test_f_a_detection_with_only_overlapping_marks_gives_no_stockpile_and_rejects_both(self) -> None:
        """RF-016-04: una capa con solo A y B solapadas no es un error de la preparación: no hay acopios y las dos marcas salen
        rechazadas (el trabajo no está vacío); el mismo trabajo, sin ninguna de las dos listas, sí lo es (error del programa)."""
        scene = self.scene
        job = scene.job((scene.a, scene.b))
        self.assertEqual(job.marks, ())
        outcome = stockpiles.detect_stockpiles(job)
        self.assertEqual(outcome.stockpiles, ())
        self.assertEqual([item.key for item in outcome.rejected], ["A", "B"])
        self.assertEqual(outcome.count, 0)
        with self.assertRaises(ValueError):
            stockpiles.StockpileJob("Acopios", "STK-001", scene.grid, scene.terrain, (), params_of())

    def test_g_the_job_keeps_its_own_rules_about_shared_cells_and_keys(self) -> None:
        """RF-016-04: el trabajo sigue sin admitir dos marcas con celdas comunes entre las que calcula (la preparación las aparta antes) ni
        una clave repetida entre las que calcula y las apartadas; una apartada que no es una ``RefusedMark`` es un ``TypeError``."""
        scene = self.scene
        with self.assertRaises(ValueError):
            stockpiles.StockpileJob("Acopios", "STK-001", scene.grid, scene.terrain, (scene.a, scene.b), params_of())
        _kept, refused = stockpiles.refuse_overlaps((scene.a, scene.b), scene.grid)
        with self.assertRaises(ValueError):
            stockpiles.StockpileJob("Acopios", "STK-001", scene.grid, scene.terrain, (mark_of("A", C_BOX, scene.grid),), params_of(),
                                    None, None, None, refused)
        with self.assertRaises(TypeError):
            stockpiles.StockpileJob("Acopios", "STK-001", scene.grid, scene.terrain, (scene.c,), params_of(), None, None, None,
                                    (scene.a,))


if __name__ == "__main__":
    unittest.main()
