# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que enseña el diálogo de «Calcular» una pista, una propuesta del trazado o una accesibilidad con muchos avisos (spec 017, T51; hallazgo H3-4 del H3; HU-017-1, HU-017-3; RF-017-14, RF-017-17,
RF-017-23).

Con una rampa de 13 curvas el resumen de «Calcular» crecía más que la ventana (1920 × 1001) y «Confirmar y crear» quedaba debajo de lo visible. Dos funciones **puras** de ``design.preview``, sin ``bpy``
ni ``blf``, recortan **solo lo que se enseña** (lo guardado en el informe de la operación, ``des_prp_``, y lo que dice el informe de la orden no pasan por ellas):

- ``limit_notices``: hasta ``SUMMARY_PER_CODE`` (3) avisos de cada código y, tras el último que se enseña de cada uno, la nota ``des.summary_more`` «… y N avisos como éste (en el informe)»;
- ``fit_summary``: un tope de **filas** (de etiqueta, ya partidas al ancho del diálogo) del resumen; lo protegido (las cifras) siempre, después **las alertas antes que las notas**, y una línea que dice
  cuántas líneas faltan.

Las pruebas, con avisos y filas hechos a mano, en el orden de sus letras:

- (a) 25 avisos de radio: se enseñan 3 y «… y 22 avisos como éste (en el informe)» justo detrás; la lista de entrada, entera y sin tocar;
- (b) cada código con su cuenta y su línea (en su sitio); con 3 o menos no cambia nada; las notas y lo exento no se recortan; el singular; lo que no es de la función es un error del programa;
- (c) las filas: bajo el tope, igual; sobre él, lo protegido y las alertas primero y las notas después, en su orden, con la línea de lo que falta y sin pasar del tope;
- (d) un aviso de alerta nunca se esconde para enseñar una nota; lo protegido se enseña aunque no quepa.
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

preview = import_geoblender("design.preview")
messages = import_geoblender("design.messages")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")


def radius(vertex: int) -> object:
    """El aviso de RF-017-14 del vértice ``vertex`` (un aviso, con su vértice, su radio y su lugar)."""
    return preview.Notice("des.road_radius_reduced", {"entity": "RDW-004", "vertex": vertex, "radius": 20.0, "fitted": 13.2, "x": 700_000.0 + vertex, "y": 4_400_000.0})


def mask(index: int) -> object:
    """Un aviso de otro código (la calzada que no queda en su rasante por las máscaras)."""
    return preview.Notice("des.road_carriageway_masks", {"entity": "RDW-004", "area": 10.0 * index, "difference": 0.4, "blocker": "Concesión", "x": 700_000.0, "y": 4_400_000.0 + index})


def stretch(index: int) -> object:
    """Una nota (gravedad ``note``)."""
    return preview.Notice("des.edge_stretch", {"stretch": index, "pairs": 3, "maximum": 1.25, "x": 700_000.0, "y": 4_400_000.0})


def codes(found: object) -> list[str]:
    return [notice.code for notice in found]


class LimitNoticesTest(unittest.TestCase):
    """``limit_notices``: hasta 3 avisos de cada código y cuántos faltan."""

    def test_a_twenty_five_radius_notices_show_three_and_say_how_many_are_missing(self) -> None:
        """RF-017-14, H3-4: una rampa con un aviso de radio por vértice (25) enseña los 3 primeros y, detrás del tercero, «… y 22 avisos como éste (en el informe)»; **los 25 siguen en la lista de
        entrada** (la que va al informe: la función no la toca), el que se enseña es de los primeros y el texto está en los dos idiomas."""
        notices = tuple(radius(vertex) for vertex in range(1, 26))
        found = preview.limit_notices(notices)
        self.assertEqual(len(found), 4)
        self.assertEqual(found[:3], notices[:3])
        self.assertEqual((found[3].code, dict(found[3].values), found[3].severity), ("des.summary_more", {"count": 22}, "warning"))
        self.assertEqual(len(notices), 25)
        self.assertEqual(found[3].text("es"), "… y 22 avisos como éste (en el informe).")
        self.assertEqual(found[3].text("en"), "… and 22 more warnings like this one (in the report).")
        self.assertIn("en el vértice 1 el radio baja de 20,0 m a 13,2 m", found[0].text("es"), "lo que se enseña lleva el vértice, el radio y su lugar enteros")
        thin = i18n.THIN_SPACE
        self.assertIn(f"(x = 700{thin}001,0 m, y = 4{thin}400{thin}000,0 m)", found[0].text("es"))

    def test_b_each_code_has_its_own_count_and_its_line_in_its_place(self) -> None:
        """RF-017-14, RF-017-22: con dos códigos mezclados cada uno cuenta aparte y su línea va **detrás del último que se enseña de su código**, no al final; con tres o menos no cambia nada (la misma
        tupla); una nota (``note``) no se recorta nunca, ni lo exento (``exempt``); un solo aviso de más dice «1 aviso»."""
        first, second = [radius(1), radius(2), radius(3), radius(4), radius(5)], [mask(1), mask(2), mask(3), mask(4)]
        mixed = (first[0], second[0], first[1], first[2], first[3], second[1], second[2], second[3], first[4])
        found = preview.limit_notices(mixed)
        self.assertEqual(codes(found), ["des.road_radius_reduced", "des.road_carriageway_masks", "des.road_radius_reduced", "des.road_radius_reduced", "des.summary_more",
                                        "des.road_carriageway_masks", "des.road_carriageway_masks", "des.summary_more"])
        self.assertEqual([dict(notice.values) for notice in found if notice.code == "des.summary_more"], [{"count": 2}, {"count": 1}])
        self.assertEqual(found[-1].text("es"), "… y 1 aviso como éste (en el informe).")
        few = (radius(1), mask(1), radius(2), radius(3))
        self.assertEqual(preview.limit_notices(few), few)
        notes = tuple(stretch(index) for index in range(1, 11))
        self.assertEqual(preview.limit_notices(notes), notes, "una nota no se recorta")
        held = tuple(radius(vertex) for vertex in range(1, 8))
        self.assertEqual(preview.limit_notices(held, exempt={"des.road_radius_reduced"}), held)
        self.assertEqual(codes(preview.limit_notices(held, per_code=1)), ["des.road_radius_reduced", "des.summary_more"])
        self.assertEqual(preview.limit_notices(iter(few)), few, "vale cualquier iterable")
        self.assertEqual(preview.limit_notices(()), ())
        nothing = preview.limit_notices((stretch(1), radius(1), radius(2), stretch(2)), per_code=0)
        self.assertEqual(codes(nothing), ["des.edge_stretch", "des.summary_more", "des.edge_stretch"], "con 0 se enseña ninguno y la línea va donde habría estado el primero")
        self.assertEqual(dict(nothing[1].values), {"count": 2})

    def test_c_what_is_not_the_functions_is_a_program_error(self) -> None:
        """Un tope negativo es un error del programa (``ValueError``); el tope por defecto es el de la tarea (3)."""
        with self.assertRaises(ValueError):
            preview.limit_notices((), per_code=-1)
        self.assertEqual(preview.SUMMARY_PER_CODE, 3)

    def test_d_the_line_of_what_is_missing_is_in_the_catalog_in_both_languages(self) -> None:
        """Principio 10: ``des.summary_more`` tiene su ``msgid`` en inglés (sin letras del español) y su texto en español con los mismos marcadores, y su singular; es un aviso (``warning``: sigue a los avisos que recorta, en ámbar, y con ellos pasa por delante de las notas cuando el resumen se corta por filas; no está en la lista que cuenta el botón «Crear con N avisos»)."""
        message = messages.MESSAGES["des.summary_more"]
        self.assertEqual(message.severity, "warning")
        for text in (message.msgid, message.one_msgid):
            self.assertEqual(set(text) & SPANISH_LETTERS, set())
        self.assertEqual(i18n.placeholders(message.msgid), i18n.placeholders(message.es))
        self.assertEqual(i18n.placeholders(message.one_msgid), i18n.placeholders(message.one_es))
        self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)


def rows_of(text: str, alert: bool) -> int:
    """Las filas de una línea de la prueba: un dígito al principio («3 …»), las que ocupa; ``more`` ocupa una."""
    return int(text.split(" ", 1)[0]) if text[:1].isdigit() else 1


def more(count: int) -> str:
    return f"… y {count} líneas más"


class FitSummaryTest(unittest.TestCase):
    """``fit_summary``: un tope de filas, con lo protegido, las alertas antes que las notas y lo que falta."""

    LINES = [("2 cifras de la cabecera", False), ("1 más de la cabecera", False), ("3 alerta A", True), ("2 nota B", False), ("3 alerta C", True), ("2 nota D", False), ("1 nota E", False)]
    """Cabecera (protegida: 2 líneas, 3 filas), alertas A y C (3 + 3) y notas B, D y E (2 + 2 + 1): 14 filas."""

    def test_a_under_the_cap_nothing_changes(self) -> None:
        """H3-4: con el resumen dentro del tope (o justo en él) no se toca ni se llama a ``more``: las pruebas de los resúmenes pequeños de siempre siguen valiendo."""
        called: list[int] = []
        found = preview.fit_summary(self.LINES, rows_of, 14, protect=2, more=lambda count: called.append(count) or "x")
        self.assertEqual(found, self.LINES)
        self.assertEqual(called, [])
        self.assertIsNot(found, self.LINES)

    def test_b_over_the_cap_the_header_and_the_alerts_stay_and_the_notes_go_first(self) -> None:
        """H3-4: sobre el tope se enseña lo protegido y **las alertas primero** (A y C), después las notas mientras quepan, **en el orden de siempre**, y una última línea con cuántas líneas faltan; con 11
        filas caben la cabecera (3), las dos alertas (6) y la línea de lo que falta (1), y una nota de 2 filas no cabe en la fila que sobra: faltan las tres notas."""
        found = preview.fit_summary(self.LINES, rows_of, 11, protect=2, more=more)
        self.assertEqual([text for text, _alert in found], ["2 cifras de la cabecera", "1 más de la cabecera", "3 alerta A", "3 alerta C", "… y 3 líneas más"])
        self.assertEqual(found[-1], ("… y 3 líneas más", False))
        self.assertLessEqual(sum(rows_of(text, alert) for text, alert in found), 11)
        roomy = preview.fit_summary(self.LINES, rows_of, 13, protect=2, more=more)
        self.assertEqual([text for text, _alert in roomy], ["2 cifras de la cabecera", "1 más de la cabecera", "3 alerta A", "2 nota B", "3 alerta C", "… y 2 líneas más"],
                         "con sitio para una nota, la primera, en su sitio entre las alertas; las otras dos faltan")
        self.assertLessEqual(sum(rows_of(text, alert) for text, alert in roomy), 13)

    def test_c_an_alert_is_never_hidden_to_show_a_note(self) -> None:
        """H3-4: si una alerta no cabe, **ninguna nota** se enseña aunque quepa (el resumen que se corta por el final de las alertas), y se dice cuántas faltan."""
        lines = [("1 cabecera", False), ("2 alerta A", True), ("4 alerta B", True), ("1 alerta C", True), ("1 nota", False)]
        found = preview.fit_summary(lines, rows_of, 6, protect=1, more=more)
        self.assertEqual([text for text, _alert in found], ["1 cabecera", "2 alerta A", "… y 3 líneas más"])
        self.assertFalse(any(text == "1 nota" or text == "1 alerta C" for text, _alert in found), "ni la nota ni la alerta pequeña que sí cabría detrás de la que no cabe")

    def test_d_what_is_protected_is_shown_even_if_it_does_not_fit(self) -> None:
        """H3-4: la cabecera (las cifras) se enseña **aunque ella sola pase del tope**: se pierde el resto y la línea de lo que falta lo dice; sin nada que cortar (todo protegido) no hay línea."""
        found = preview.fit_summary(self.LINES, rows_of, 2, protect=2, more=more)
        self.assertEqual([text for text, _alert in found], ["2 cifras de la cabecera", "1 más de la cabecera", "… y 5 líneas más"])
        everything = preview.fit_summary(self.LINES[:2], rows_of, 1, protect=2, more=more)
        self.assertEqual(everything, self.LINES[:2], "todo protegido: no hay nada que decir que falte")
        self.assertEqual(preview.fit_summary([], rows_of, 5, protect=0, more=more), [])

    def test_e_what_the_function_does_not_take_is_a_program_error(self) -> None:
        """Un tope que no es positivo o una protección negativa es un error del programa (``ValueError``); el tope por defecto cabe en la ventana del H3 (1001 px de 20 px por fila: 50 filas como mucho)."""
        with self.assertRaises(ValueError):
            preview.fit_summary(self.LINES, rows_of, 0, protect=0, more=more)
        with self.assertRaises(ValueError):
            preview.fit_summary(self.LINES, rows_of, 5, protect=-1, more=more)
        self.assertTrue(0 < preview.SUMMARY_ROWS < 1001 // 20)
        with self.assertRaises(ValueError):
            preview.fit_summary(self.LINES, rows_of, 5, protect=0, more=more, weights=[1, 1])

    def test_f_a_line_that_stands_for_others_counts_them_when_it_is_hidden(self) -> None:
        """H3-4: la línea «… y 22 avisos como éste» resume 22 líneas del resumen entero (``weights``): si el tope la esconde, faltan 22 y no una; si se enseña, no cuenta (las resume ella); sin pesos,
        cada línea cuenta una."""
        lines = [("1 cabecera", False), ("1 alerta A", True), ("1 … y 22 como éste", True), ("2 nota", False)]
        weights = [1, 1, 22, 1]
        hidden = preview.fit_summary(lines, rows_of, 3, protect=1, more=more, weights=weights)
        self.assertEqual(hidden, [("1 cabecera", False), ("1 alerta A", True), ("… y 23 líneas más", False)], "la línea de las 22 no cabe: faltan las 22 y la nota")
        shown = preview.fit_summary(lines, rows_of, 4, protect=1, more=more, weights=weights)
        self.assertEqual(shown, [("1 cabecera", False), ("1 alerta A", True), ("1 … y 22 como éste", True), ("… y 1 líneas más", False)], "enseña la línea de las 22 y solo falta la nota")
        self.assertEqual(preview.fit_summary(lines, rows_of, 3, protect=1, more=more)[-1], ("… y 2 líneas más", False), "sin pesos, cada línea cuenta una")


if __name__ == "__main__":
    unittest.main()
