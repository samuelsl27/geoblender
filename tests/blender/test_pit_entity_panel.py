# SPDX-License-Identifier: GPL-3.0-or-later
"""La barra N con la corta por bancos: lo que escribe y dibuja, sin proyecto (spec 018, T34; HU-018-1, HU-018-4; RF-018-26, RF-018-34, RF-015-25; plan 018 §5.5; comprobación manual M5).

La barra N «Entidad» y «Elemento activo» enseñan de **una corta** (el objeto ``DESIGN_ENTITY`` de su ``des_epr_``), además de lo de la 015, su modo y cuántos bancos tiene y por qué paró, las cotas de
fondo y de coronación, la longitud de pies y de crestas, las áreas, el volumen de corte y **el de cada banco**, la línea de cielo con sus distancias, las rampas (longitud, pendiente media y máxima) y
**la lista de hallazgos con su «Ir a»** (cada uno en su lugar), y el estado con su causa (al día, obsoleta, descartada o «apoyo retirado»: ``des_panels._entity_state_line``). Lo de con proyecto (cada
estado de la corta, leído de lo guardado y las órdenes reales) es un hito (``tests/blender/milestone_pit_entity_panel.py``); aquí, en el «verde» y **sin proyecto**, con lo que lee el dominio puesto a
mano (``design.pit_card``, que prueba ``tests/unit/design/test_pit_card.py``):

- RF-015-25, RF-018-31 (a): las líneas de una corta, en español y en inglés, sin llaves sin sustituir; sin informe, lo dice y no inventa cifras.
- RF-018-26 (b): **los hallazgos, en alerta y con su «Ir a»** (el lugar con el radio de ``place_of``); una corta sin hallazgos lo dice; una lista larga se corta a ``LIST_LIMIT`` con una nota.
- RF-015-25, RF-018-29 (c): la línea de cielo (o que no tiene) y las rampas, con su «Ir a».
- RF-015-28, RF-015-25 (d): el estado de la corta (al día, obsoleta con su causa, descartada y «apoyo retirado») y que su tipo reparte a sus líneas; una sin calcular no tiene ninguna.
- RF-018-34 (e): el modo y su color en la vista; el dibujo de la barra N con el botón «Ir a» solo en la fila que tiene lugar.
- Principio 8 (z): desactivar Geoblender deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.fake_layout import FakeLayout


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


NEW_MSGIDS = (
    "The project has no report of this pit", "Mode «{mode}» · benches: {benches}", "Stopped by: {criterion}", "it comes out to the surface", "it reaches the top elevation",
    "the floor reaches the minimum width", "it reaches the bottom elevation", "it reaches the maximum number of benches", "Bottom elevation {bottom} m · top elevation {top} m",
    "Length of the toes {foot} m · of the crests {crest} m", "Area: berms {berm} m² · floor {floor} m² · moved {moved} m²", "Cut volume: {cut} m³", "Volume by bench",
    "Bench {bench}: elevation from {foot} to {crest} m · cut {cut} m³", "… and {more} more benches (all of them are in the table of the pit)",
    "Skyline: parts {parts} · length {length} m · encloses {area} m² · elevation from {low} to {high} m", "Distance from the skyline to the legal limit: {distance} m",
    "Distance from the skyline to the perimeter of the works: {distance} m", "The pit has no skyline", "Ramp «{code}» · bench {bench}: length {length} m · mean gradient {mean} % · maximum {max} %",
    "Findings", "No findings: everything that was measured is within its limits", "… and {more} more findings (the whole list is in the findings of the pit)")
"""Los textos que añade la barra N de la corta (``messages.toml``)."""
WEST, NORTH = 700_000.0, 4_400_100.0


class PitSidebarTest(unittest.TestCase):
    """La extensión habilitada una vez; el lector del dominio, puesto a mano (sin proyecto)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.panels = _module("bl.ui.des_panels")
        cls.pit_panels = _module("bl.ui.pit_panels")
        cls.pit_card = _module("design.pit_card")
        cls.pit_model = _module("design.pit_model")
        cls.entities = _module("design.entities")
        cls.entity_views = _module("bl.scene.entity_views")
        cls.i18n = _module("core.i18n")
        cls.constraint_panels = _module("bl.ui.constraint_panels")

    def setUp(self) -> None:
        self.addCleanup(self.i18n.set_language, self.i18n.language())

    # --- Lo que lee el dominio, puesto a mano --------------------------------------------------------

    def finding(self, kind: str, bench: int | None, value: float | None, limit: float | None, unit: str, offset: float = 0.0, detail: str = "") -> object:
        return self.pit_model.Finding(kind, value, limit, (WEST + 10.0 + offset, NORTH - 20.0), bench, unit, detail)

    def facts(self, **changes: object) -> object:
        """Los datos guardados de una corta de 3 bancos con su línea de cielo, una rampa y dos hallazgos."""
        values: dict[str, object] = {
            "figures": {"benches": 3.0, "z_bottom_m": 100.0, "z_top_m": 130.0, "len_foot_m": 820.5, "len_crest_m": 900.0, "area_berm_m2": 4200.0, "area_floor_m2": 1500.0, "cut_m3": 125000.0,
                        "area_m2": 9800.0, "sky_parts": 1.0, "sky_len_m": 410.0, "sky_area_m2": 9000.0, "sky_z_min_m": 100.5, "sky_z_max_m": 129.75, "sky_dist_legal_m": 15.5,
                        "sky_dist_perimeter_m": 22.0},
            "stop": "surface",
            "benches": (self.pit_card.BenchRow(1, 100.0, 110.0, 200.0, 240.0, 1500.0, 1500.0, 40000.0), self.pit_card.BenchRow(2, 110.0, 120.0, 300.0, 330.0, 2000.0, None, 50000.0)),
            "findings": (self.finding("face_slope", 2, 74.5, 72.0, "°"), self.finding("unexcavated", None, 350.0, 0.0, "m²", 20.0)),
            "ramps": (self.pit_card.RampRow("R1", 1, 40.0, 7.5, 20.0, WEST + 5.0, NORTH - 5.0),),
            "notices": ()}
        values.update(changes)
        return self.pit_card.PitFacts(**values)

    def pit_lines(self, language: str, facts: object | None, *, mode: object = "up") -> list:
        """Las líneas de la barra N de una corta con ``facts`` puesto a mano."""
        self.i18n.set_language(language)
        entry = SimpleNamespace(operation_uid="op", record=SimpleNamespace(state="current", code="PIT-001", kind="pit"))
        stored = {"mode": SimpleNamespace(value=mode)}
        with mock.patch.object(self.pit_card, "read_pit_facts", return_value=facts):
            return self.pit_panels.pit_card_lines(None, None, SimpleNamespace(uid="v1", code="V01"), entry, stored)

    def texts(self, lines: list) -> list[str]:
        return [line.text for line in lines]

    def n(self, value: float, decimals: int) -> str:
        return self.i18n.format_number(value, decimals)

    # --- a: la corta ---------------------------------------------------------------------------------

    def test_a_the_pit_says_what_the_project_stored_in_both_languages(self) -> None:
        """RF-015-25, RF-018-31 (M5): la corta enseña su modo y sus bancos, por qué paró, las cotas de fondo y de coronación, la longitud de pies y de crestas, las áreas y el volumen de corte, y el
        volumen **de cada banco**; en español y en inglés, con coma o punto decimal, sin llaves sin sustituir y sin ámbar en las cifras."""
        lines = self.pit_lines("es", self.facts())
        spanish = self.texts(lines)
        self.assertEqual(spanish[0], "Corta")
        self.assertEqual(spanish[1], "Modo «Ascendente» · bancos: 3")
        self.assertEqual(spanish[2], "Parada por: sale a la superficie")
        self.assertEqual(spanish[3], "Cota de fondo 100,00 m · cota de coronación 130,00 m")
        self.assertEqual(spanish[4], "Longitud de pies 820,5 m · de crestas 900,0 m")
        self.assertEqual(spanish[5], f"Áreas: bermas {self.n(4200.0, 0)} m² · fondo {self.n(1500.0, 0)} m² · con movimiento {self.n(9800.0, 0)} m²")
        self.assertEqual(spanish[6], f"Volumen de corte: {self.n(125000.0, 0)} m³")
        self.assertIn("Volumen por banco", spanish)
        self.assertIn(f"Banco 1: cota de 100,00 a 110,00 m · corte {self.n(40000.0, 0)} m³", spanish)
        self.assertIn(f"Banco 2: cota de 110,00 a 120,00 m · corte {self.n(50000.0, 0)} m³", spanish)
        english = self.texts(self.pit_lines("en", self.facts(), mode="down"))
        self.assertEqual(english[1], "Mode «Descending» · benches: 3")
        self.assertEqual(english[3], "Bottom elevation 100.00 m · top elevation 130.00 m")
        self.assertEqual(english[4], "Length of the toes 820.5 m · of the crests 900.0 m")
        self.assertIn("Cut volume: 125,000 m³", english)
        for shown in (*spanish, *english):
            self.assertNotIn("{", shown)
        self.assertFalse(any(line.alert for line in lines[:7]), "las cifras no van en ámbar")

    def test_a_b_every_stop_criterion_has_its_text_and_missing_data_do_not_invent_figures(self) -> None:
        """RF-018-13, RF-015-25: los cinco criterios de parada con su texto; sin informe en el proyecto lo dice y no inventa cifras; una cifra que falta se enseña como «no enseñada», no como 0."""
        shown = {"surface": "sale a la superficie", "top_level": "llega a la cota de coronación", "floor_width": "el fondo llega al ancho mínimo", "bottom_level": "llega a la cota de fondo",
                 "max_benches": "llega al número máximo de bancos"}
        for code, text in shown.items():
            with self.subTest(stop=code):
                self.assertIn(f"Parada por: {text}", self.texts(self.pit_lines("es", self.facts(stop=code))))
        self.assertFalse(any(text.startswith("Parada") for text in self.texts(self.pit_lines("es", self.facts(stop=None)))))
        missing = self.pit_lines("es", None)
        self.assertEqual(self.texts(missing), ["Corta", "El proyecto no tiene el informe de esta corta"])
        self.assertEqual(missing[-1].kind, self.panels.ROW_NONE)
        bare = self.texts(self.pit_lines("es", self.facts(figures={}, benches=(), findings=(), ramps=())))
        self.assertTrue(any(text.startswith("Cota de fondo ") and "0,00" not in text for text in bare), bare)

    # --- b: los hallazgos ----------------------------------------------------------------------------

    def test_b_findings_are_listed_in_alert_each_with_its_go_to(self) -> None:
        """RF-018-26 (M5): la lista de hallazgos lleva su título con cuántos son, **cada uno en alerta y con su «Ir a»** (``ROW_PLACE``: el lugar y el radio de ``place_of``; el del área sin excavar, con
        su área para el radio), con su banco; sin hallazgos dice que todo lo medido está dentro de sus límites; una lista larga se corta a ``LIST_LIMIT`` con una nota que dice cuántos faltan."""
        lines = self.pit_lines("es", self.facts())
        at = self.texts(lines).index("Hallazgos (2)")
        found = lines[at + 1:at + 3]
        self.assertEqual([line.kind for line in found], [self.panels.ROW_PLACE] * 2)
        self.assertTrue(all(line.alert for line in found))
        self.assertEqual(found[0].text, "Inclinación real de la cara fuera del límite: 74,5 ° (límite 72,0 °) · banco 2")
        self.assertEqual(found[0].uid, ";".join(self.constraint_panels.place_of(WEST + 10.0, NORTH - 20.0, 0.0)))
        self.assertEqual(found[1].uid, ";".join(self.constraint_panels.place_of(WEST + 30.0, NORTH - 20.0, 350.0)), "el área sin excavar da el radio del encuadre")
        clean = self.pit_lines("es", self.facts(findings=()))
        self.assertEqual([(line.kind, line.text, line.alert) for line in clean[-2:]],
                         [(self.panels.ROW_HEADING, "Hallazgos (0)", False), (self.panels.ROW_NONE, "Sin hallazgos: todo lo medido está dentro de sus límites", False)])
        limit = self.panels.LIST_LIMIT
        many = self.pit_lines("es", self.facts(findings=tuple(self.finding("berm_width", number, 3.0, 5.0, "m", float(number)) for number in range(1, limit + 6))))
        places = [line for line in many if line.kind == self.panels.ROW_PLACE and line.text.startswith("Berma real")]
        self.assertEqual(len(places), limit)
        self.assertIn("… y 5 hallazgos más (la lista entera está en los hallazgos de la corta)", self.texts(many))
        english = self.texts(self.pit_lines("en", self.facts()))
        self.assertIn("Findings (2)", english)
        self.assertIn("Real face slope out of the limit: 74.5 ° (limit 72.0 °) · bench 2", english)

    def test_b_b_a_bench_without_a_profile_is_a_finding_and_not_a_pass(self) -> None:
        """RF-018-26: un banco sin perfil sale como hallazgo (con su banco y su lugar), no como «cumple», y la corta no dice «sin hallazgos»."""
        lines = self.pit_lines("es", self.facts(findings=(self.finding("no_profile", 4, None, None, "", 0.0, "perímetro"),)))
        text = self.texts(lines)
        self.assertIn("Banco sin perfil · banco 4", text)
        self.assertFalse(any(item.startswith("Sin hallazgos") for item in text))

    # --- c: la línea de cielo y las rampas -------------------------------------------------------------

    def test_c_the_skyline_and_the_ramps(self) -> None:
        """RF-018-29, RF-018-31, RF-015-25: la línea de cielo con sus partes, longitud, área y cotas y las distancias al límite legal y al perímetro (solo las que hay); sin línea de cielo lo dice; las
        rampas con su título, su longitud, su pendiente media y la máxima y su «Ir a» al inicio; sin rampas, «Nada que enseñar»."""
        lines = self.pit_lines("es", self.facts())
        text = self.texts(lines)
        self.assertIn(f"Línea de cielo: partes 1 · longitud {self.n(410.0, 0)} m · encierra {self.n(9000.0, 0)} m² · cota de 100,50 a 129,75 m", text)
        self.assertIn("Distancia de la línea de cielo al límite legal: 15,5 m", text)
        self.assertIn("Distancia de la línea de cielo al perímetro de actuación: 22,0 m", text)
        self.assertIn("Rampas (1)", text)
        ramp = lines[text.index("Rampas (1)") + 1]
        self.assertEqual((ramp.kind, ramp.text, ramp.alert), (self.panels.ROW_PLACE, "Rampa «R1» · banco 1: longitud 40,0 m · pendiente media 7,50 % · máxima 20,00 %", False))
        self.assertEqual(ramp.uid, ";".join(self.constraint_panels.place_of(WEST + 5.0, NORTH - 5.0, 0.0)))
        figures = {key: value for key, value in self.facts().figures.items() if not key.startswith("sky_")}
        bare = self.pit_lines("es", self.facts(figures=figures, ramps=()))
        self.assertIn("La corta no tiene línea de cielo", self.texts(bare))
        self.assertEqual([(line.kind, line.text) for line in bare[self.texts(bare).index("Rampas (0)"):][:2]], [(self.panels.ROW_HEADING, "Rampas (0)"), (self.panels.ROW_NONE, "Nada que enseñar")])
        no_perimeter = {key: value for key, value in self.facts().figures.items() if key != "sky_dist_perimeter_m"}
        only_legal = self.texts(self.pit_lines("es", self.facts(figures=no_perimeter)))
        self.assertIn("Distancia de la línea de cielo al límite legal: 15,5 m", only_legal)
        self.assertFalse(any("perímetro" in item for item in only_legal), "solo la distancia que se guardó")

    def test_c_b_the_stored_warnings_come_after_the_figures(self) -> None:
        """RF-018-31: los avisos guardados del cálculo salen en su orden (el aviso, en alerta; la nota, no)."""
        preview = _module("design.preview")
        notices = (preview.Notice("des.pit_ramp_mean_gradient", {"mean": 9.5, "limit": 8.0}),)
        lines = self.pit_lines("es", self.facts(notices=notices))
        found = [line for line in lines if "pendiente media" in line.text and line.kind == self.panels.ROW_FIELD]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].alert, notices[0].severity == "warning")

    # --- d: el estado y el reparto por tipo ------------------------------------------------------------

    def state_line(self, state: str, cause: str | None = None) -> object:
        self.i18n.set_language("es")
        entry = SimpleNamespace(record=SimpleNamespace(state=state, code="PIT-001"))
        with mock.patch.object(self.entities, "stale_reason", return_value=cause):
            return self.panels._entity_state_line(None, None, SimpleNamespace(uid="v1"), entry)

    def test_d_the_state_of_the_pit_says_its_cause(self) -> None:
        """RF-015-25, RF-015-28: la corta al día, obsoleta (con su causa, en alerta), con el apoyo retirado (con su causa, en alerta) y descartada (en alerta) tienen cada una su línea de estado."""
        self.assertEqual((self.state_line("current").text, self.state_line("current").alert), ("Al día", False))
        stale = self.state_line("stale", "La superficie de partida «des_psf_carga» cambió")
        self.assertEqual((stale.text, stale.alert), ("La superficie de partida «des_psf_carga» cambió", True))
        removed = self.state_line("support_removed", "Se soltó el apoyo en «Relleno»")
        self.assertEqual((removed.text, removed.alert), ("Se soltó el apoyo en «Relleno»", True))
        discarded = self.state_line("discarded")
        self.assertTrue(discarded.alert)
        self.assertTrue(discarded.text.startswith("Descartada"))

    def test_d_b_the_type_lines_dispatch_a_pit_and_an_uncalculated_one_has_none(self) -> None:
        """RF-015-25: ``_type_lines`` reparte una corta a su ficha y una sin calcular (sin operación) no tiene ninguna."""
        self.i18n.set_language("es")
        entry = SimpleNamespace(operation_uid="op", record=SimpleNamespace(state="current", code="PIT-001", kind="pit"))
        stored = {"mode": SimpleNamespace(value="down")}
        with mock.patch.object(self.pit_card, "read_pit_facts", return_value=self.facts()):
            lines = self.panels._type_lines(None, None, SimpleNamespace(uid="v1", code="V01"), entry, stored)
        self.assertEqual(lines[0].text, "Corta")
        self.assertEqual(lines[1].text, "Modo «Descendente» · bancos: 3")
        fresh = SimpleNamespace(operation_uid=None, record=SimpleNamespace(state="uncalculated", code="PIT-002", kind="pit"))
        self.assertEqual(self.panels._type_lines(None, None, SimpleNamespace(uid="v1"), fresh, {}), [])

    # --- e: el color, el modo y el dibujo -----------------------------------------------------------------

    def test_e_the_pit_has_its_own_color_its_modes_their_names_and_all_texts_are_translated(self) -> None:
        """RF-018-34: el objeto de una corta tiene su color en la vista (no el gris de «otro»), el modo de la corta se llama «Ascendente» y «Descendente» también en sus parámetros, y todos los textos
        nuevos están traducidos (con las llaves de ``format`` que tiene el inglés)."""
        self.assertIn("pit", self.entity_views.COLORS)
        self.assertNotEqual(self.entity_views.COLORS["pit"], self.entity_views.OTHER_COLOR)
        self.assertEqual(self.panels._CHOICES_TEXT["mode"]["up"], "Ascending")
        self.assertEqual(self.panels._CHOICES_TEXT["mode"]["down"], "Descending")
        self.assertEqual(self.i18n.untranslated(list(NEW_MSGIDS)), [])
        description = ("A design entity (a platform, a haul road, the removal of a stockpile, a buttress, a supported body or a pit by benches) or a stockpile detection, drawn by its footprint (a haul road, also by its 3D axis)")
        self.assertEqual(self.i18n.untranslated([description]), [])

    def drawn(self, rows: list) -> FakeLayout:
        self.i18n.set_language("es")
        shown = SimpleNamespace(item_uid="u1", item_found=True, item_title="Corta «Cantera» (PIT-001)",
                                item=[SimpleNamespace(kind=line.kind, name=line.text, alert=line.alert, uid=line.uid) for line in rows])
        layout = FakeLayout()
        self.assertTrue(self.panels._draw_item(layout, shown, "u1", 400.0))
        return layout

    def test_e_b_each_finding_and_ramp_draws_its_go_to_button(self) -> None:
        """RF-018-26 (M5): en la barra N cada fila de hallazgo y de rampa dibuja su texto y **su botón «Ir a»** (``geoblender.core_go_to_place``) con la ``x``, la ``y`` y el radio de su lugar, y las
        cifras sin lugar no lo dibujan; los hallazgos, en alerta."""
        lines = self.pit_lines("es", self.facts())
        layout = self.drawn(lines)
        buttons = layout.of_kind("operator")
        with_place = [line for line in lines if line.kind == self.panels.ROW_PLACE]
        self.assertEqual(len(with_place), 3)
        self.assertEqual({button.target for button in buttons}, {self.constraint_panels.GO_TO_PLACE})
        self.assertEqual([(button.properties.x, button.properties.y, button.properties.radius) for button in buttons], [tuple(line.uid.split(";")) for line in with_place])
        alerts = {item.text for item in layout.of_kind("label") if item.alert}
        self.assertTrue(any("Inclinación real" in text for text in alerts))
        self.assertIn("Volumen de corte: " + self.n(125000.0, 0) + " m³", layout.texts())

    # --- z: el registro --------------------------------------------------------------------------------

    def test_z_disabling_geoblender_leaves_blender_as_it_was(self) -> None:
        """Principio 8 (``geoblender/AGENTS.md``, Registro): con la barra N de la corta, desactivar Geoblender deja la huella entera de Blender como la del principio de la sesión."""
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
