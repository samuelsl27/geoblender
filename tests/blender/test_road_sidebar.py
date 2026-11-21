# SPDX-License-Identifier: GPL-3.0-or-later
"""La barra N con la pista y la accesibilidad: lo que escribe y dibuja, sin proyecto (spec 017, T31b; HU-017-1, HU-017-3; RF-015-25, RF-017-23, RF-017-25, RF-017-17, RF-017-22, H2-2;
plan 017 §5.5; comprobación manual M4).

La barra N «Entidad» y «Elemento activo» enseñan de **una pista** (el objeto ``DESIGN_ENTITY`` de su ``des_epr_``) su modo y su perfil, la longitud y las cotas, las pendientes con su abscisa, el radio
mínimo, la calzada y la sección, el corte y el relleno de la sección y del borde, lo que confirmó la persona y, **en alerta, la causa y la salida de una pista obsoleta por otro diseño que lee**
(H2-2) y que la capa de ejes para QGIS está marcada; y de **una accesibilidad** (el objeto ``DESIGN`` de su ``des_acc_``: la barra N «Diseño») las cotas alcanzables y las tres listas de tramos de berma,
plataformas y zonas «requiere acceso» comunicados o no, con su «Ir a». Lo de con proyecto (cada estado de cada tipo, leído de lo guardado) cuesta ≈ 15 s de mundo y es un hito
(``tests/blender/milestone_road_sidebar.py``, P-12); aquí, en el «verde» y **sin proyecto**, con lo que lee el dominio puesto a mano (``design.road_card``, que prueba ``tests/unit/design/test_road_card.py``):

- RF-015-25, RF-017-23, RF-017-17, RF-017-22 (a): las líneas de una pista —modo y perfil, longitud y cotas, pendientes con su abscisa y su lugar, el radio mínimo o «sin curvas», la calzada y la sección,
  el corte y el relleno **de la sección y del borde**, la pared, lo que se confirmó y los avisos— en español y en inglés; el aviso de confirmar la media no se repite junto a lo confirmado.
- RF-015-25, H2-2 (b): una pista **obsoleta por otro diseño que lee** dice, en alerta, **la causa y la salida** (rehacerla sobre la superficie de ese diseño o descartarla); una al día, no; y si la capa de
  ejes de pistas está marcada, lo dice y por qué; ningún texto promete que editar un campo de la capa propuesta no deja obsoleta la pista.
- RF-015-25, RF-017-25 (c): las listas de la accesibilidad: **las que no se comunican, primero y en alerta**, cada una con su «Ir a» (``ROW_PLACE``: ``x;y;radio``, el de ``constraint_panels.place_of``);
  la zona comunicada, sin lugar, sin «Ir a»; una lista larga se corta a ``LIST_LIMIT`` con una nota; sin resultado guardado, lo dice.
- RF-017-25 (d): el dibujo de la barra N de una fila con «Ir a» (un botón con su lugar) y de una sin lugar (sin botón).
- Principio 8 (z): desactivar Geoblender deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

from tests.support import blender_ext
from tests.support.fake_layout import FakeLayout


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


NEW_MSGIDS = (
    "The project has no report of this road", "Mode «{mode}» · profile «{profile}»", "Length {length} m · elevation {start} m at the start and {end} m at the end",
    "Carriageway {width} m · section {section} m", "Section: cut {cut} m³ · fill {fill} m³; edge: cut {edge_cut} m³ · fill {edge_fill} m³; net {net} m³",
    "The mean gradient, {mean} %, passed the {limit} % of the profile: confirmed by {person} on {date}",
    "{area} m² of the carriageway did not end up on the level profile: confirmed by {person} on {date} (largest difference {difference} m)",
    "It reads another design of the version that changed, {designs}: recalculating the road does not settle it if that design now rests on it. "
    "Redo the road on the surface of that design, or discard it",
    "The layer of the axes of the roads for QGIS is marked: it still says what this road was before (its state, its profile or its class), because a change such as the value of a "
    "profile does not bring it up to date at once; the next order on roads or «Recompute the stale results» does",
    "… and {more} more (the whole list is in the tables of the accessibility)", "The project has no result of this accessibility", "Surface: «{surface}»",
    "Nothing is reachable from the entry points", "Reachable elevations: from {low} to {high} m · {area} m²",
    "Lowest elevation reachable over the final surface «{final}» of the quarry: {level} m",
    "Communicated · berm stretches: {berms} of {berms_total} · platforms: {platforms} of {platforms_total} · zones that require access: {zones} of {zones_total}")
"""Los textos que añade la barra N de la pista y de la accesibilidad (``messages.toml``)."""
WEST, NORTH = 700_000.0, 4_400_100.0


class SidebarTextsTest(unittest.TestCase):
    """La extensión habilitada una vez; los lectores del dominio, puestos a mano (sin proyecto)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.panels = _module("bl.ui.des_panels")
        cls.road_card = _module("design.road_card")
        cls.preview = _module("design.preview")
        cls.road_store = _module("design.road_store")
        cls.access_store = _module("design.access_store")
        cls.i18n = _module("core.i18n")
        cls.constraint_panels = _module("bl.ui.constraint_panels")

    def setUp(self) -> None:
        self.addCleanup(self.i18n.set_language, self.i18n.language())

    # --- Lo que lee el dominio, puesto a mano -------------------------------------------------------

    def facts(self, **changes: object) -> object:
        """Los datos guardados de una pista de 120 m con dos curvas (de 25 m el menor radio), la pendiente máxima del 8,4 % a 64 m y una pared de 2,5 m."""
        values: dict[str, object] = {
            "length_m": 120.0, "z_start_m": 100.5, "z_end_m": 107.25, "gradient_mean_pct": 5.6, "gradient_max_pct": 8.4, "gradient_max_station_m": 64.0,
            "gradient_max_place": (700064.5, 4400030.5), "curves": 2, "radius_min_m": 25.0, "width_m": 10.5, "section_m": 11.5, "section_cut_m3": 410.0, "section_fill_m3": 95.0,
            "edge_cut_m3": 120.0, "edge_fill_m3": 40.0, "net_m3": 395.0, "wall_max_m": 2.5, "wall_place": (700070.0, 4400040.0), "confirmed": None, "notices": ()}
        values.update(changes)
        return self.road_card.RoadFacts(**values)

    def road_lines(self, language: str, facts: object | None, *, state: str = "current", others: tuple[str, ...] = (), marked: bool = False, mode: object = "trace") -> list:
        """Las líneas de la barra N de una pista con ``facts`` y lo demás que lee (el nombre de su perfil, los otros diseños y la marca de la capa), puesto a mano."""
        self.i18n.set_language(language)
        entry = SimpleNamespace(operation_uid="op", record=SimpleNamespace(state=state, code="RDW-001"))
        stored = {"mode": SimpleNamespace(value=mode), "profile": SimpleNamespace(value="pista_principal")}
        with (mock.patch.object(self.road_card, "read_road_facts", return_value=facts), mock.patch.object(self.road_card, "profile_name", return_value="Pista principal"),
              mock.patch.object(self.road_card, "stale_other_designs", return_value=others) as other, mock.patch.object(self.road_card, "marked_layer", return_value=marked)):
            found = self.panels._road_card_lines(None, None, SimpleNamespace(uid="v1", code="V01"), entry, stored)
            self.called = other.called
        return found

    def texts(self, lines: list) -> list[str]:
        return [line.text for line in lines]

    def n(self, value: float, decimals: int) -> str:
        """Un número como lo escribe la interfaz en el idioma de ahora (con el espacio fino de los miles en español)."""
        return self.i18n.format_number(value, decimals)

    # --- a: la pista --------------------------------------------------------------------------------

    def test_a_the_road_says_what_the_project_stored_in_both_languages(self) -> None:
        """RF-015-25, RF-017-23, RF-017-17 (M4): la pista enseña su modo y su perfil, la longitud y las cotas, la pendiente media y la máxima con su abscisa y su lugar, el radio mínimo, la calzada y la
        sección, el corte y el relleno **de la sección y del borde** con el neto y la pared del borde (en alerta); en español y en inglés, con coma o punto decimal, sin llaves sin sustituir."""
        spanish = self.texts(self.road_lines("es", self.facts()))
        self.assertEqual(spanish[0], "Pista")
        self.assertEqual(spanish[1], "Modo «Trazar» · perfil «Pista principal»")
        self.assertEqual(spanish[2], "Longitud 120,0 m · cota 100,50 m al principio y 107,25 m al final")
        self.i18n.set_language("es")
        self.assertEqual(spanish[3], f"Pendiente: media del 5,60 % · máxima del 8,40 % en la abscisa 64,0 m, en ({self.n(700064.5, 1)}, {self.n(4400030.5, 1)})")
        self.assertEqual(spanish[4], "Radio mínimo de 25,0 m en 2 curvas")
        self.assertEqual(spanish[5], "Calzada 10,50 m · sección 11,50 m")
        self.assertEqual(spanish[6], "Sección: desmonte 410 m³ · terraplén 95 m³; borde: desmonte 120 m³ · terraplén 40 m³; neto 395 m³")
        self.assertEqual(spanish[7], f"Pared de hasta 2,5 m en el borde, en torno a x = {self.n(700070.0, 0)} m, y = {self.n(4400040.0, 0)} m")
        english = self.texts(self.road_lines("en", self.facts()))
        self.assertEqual(english[1], "Mode «Trace» · profile «Pista principal»")
        self.assertEqual(english[2], "Length 120.0 m · elevation 100.50 m at the start and 107.25 m at the end")
        self.assertEqual(english[5], "Carriageway 10.50 m · section 11.50 m")
        self.assertEqual(english[6], "Section: cut 410 m³ · fill 95 m³; edge: cut 120 m³ · fill 40 m³; net 395 m³")
        for shown in (*spanish, *english):
            self.assertNotIn("{", shown)
        lines = self.road_lines("es", self.facts())
        self.assertEqual([line.alert for line in lines], [False] * 7 + [True], "solo la pared va en alerta")

    def test_a_b_the_modes_curves_and_missing_data_have_their_own_texts(self) -> None:
        """RF-015-25, RF-017-23: los tres modos con su nombre del diálogo («Trazar», «Sobre un eje», «Eje 3D»); sin curvas, «el eje es una recta»; con una curva, en singular; sin pared no hay línea de pared; sin
        informe en el proyecto, lo dice y no inventa cifras."""
        for mode, shown in (("trace", "Trazar"), ("on_axis", "Sobre un eje"), ("axis_3d", "Eje 3D")):
            with self.subTest(modo=mode):
                self.assertIn(f"Modo «{shown}»", self.road_lines("es", self.facts(), mode=mode)[1].text)
        straight = self.texts(self.road_lines("es", self.facts(curves=0, radius_min_m=None, wall_max_m=None, wall_place=None)))
        self.assertIn("Sin curvas: el eje es una recta", straight)
        self.assertFalse(any(text.startswith("Pared") for text in straight))
        self.assertIn("Radio mínimo de 30,0 m en 1 curva", self.texts(self.road_lines("es", self.facts(curves=1, radius_min_m=30.0))))
        missing = self.road_lines("es", None)
        self.assertEqual(self.texts(missing), ["Pista", "Modo «Trazar» · perfil «Pista principal»", "El proyecto no tiene el informe de esta pista"])
        self.assertEqual(missing[-1].kind, self.panels.ROW_NONE)

    def test_a_c_what_the_person_confirmed_and_the_stored_warnings(self) -> None:
        """RF-017-17, RF-017-22: la pendiente media por encima de pm que la persona confirmó sale con su límite, quién, cuándo y su motivo, y la calzada fuera de su rasante con su área y su diferencia
        (los dos en alerta); los avisos guardados salen en su orden (el aviso, en alerta; la nota, no) y **el aviso de confirmar la media no se repite** junto a lo confirmado."""
        confirmed = self.road_store.RoadConfirmed("Ana", "2026-11-21T10:00:00Z", 5.6, 5.0, "El acceso es corto", 80.0, 0.125)
        notices = (self.preview.Notice("des.road_mean_gradient", {"entity": "Pista", "mean": 5.6, "limit": 5.0, "stretches": ()}), self.preview.Notice("des.access_nothing_reached", {"entity": "Pista"}),
                   self.preview.Notice("des.access_levels", {"entity": "Pista", "z_min": 100.5, "z_max": 130.25, "area": 1320.0}))
        lines = self.road_lines("es", self.facts(confirmed=confirmed, notices=notices))
        found = {line.text: line.alert for line in lines}
        self.assertIn("La pendiente media, 5,60 %, pasaba del 5,00 % del perfil: confirmado por Ana el 2026-11-21 · Motivo: El acceso es corto", found)
        self.assertIn("80 m² de la calzada no quedaban en su rasante: confirmado por Ana el 2026-11-21 (mayor diferencia 0,125 m)", found)
        self.assertTrue(found["La pendiente media, 5,60 %, pasaba del 5,00 % del perfil: confirmado por Ana el 2026-11-21 · Motivo: El acceso es corto"])
        texts = self.texts(lines)
        self.assertFalse(any("no se crea sin su confirmación" in text for text in texts), "el aviso de confirmar la media no se repite: ya está confirmada")
        self.assertEqual([(line.text[:22], line.alert) for line in lines[-2:]], [("Accesibilidad «Pista»:", True), ("Cotas alcanzables de 1", False)], "los demás avisos, sí, en su orden: el aviso en alerta y la nota no")
        english = self.texts(self.road_lines("en", self.facts(confirmed=confirmed)))
        self.assertIn("The mean gradient, 5.60 %, passed the 5.00 % of the profile: confirmed by Ana on 2026-11-21 · Reason: El acceso es corto", english)

    # --- b: la causa y la salida de H2-2, y la capa marcada --------------------------------------------

    def test_b_a_road_stale_by_another_design_says_the_cause_and_the_way_out(self) -> None:
        """RF-015-25, H2-2 (decisión de la sesión principal): una pista **obsoleta** que lee otro diseño que cambió dice, en alerta, **la causa** (qué diseño) y **la salida**: rehacerla sobre la
        superficie de ese diseño o descartarla; una al día, no lo pregunta siquiera; una obsoleta sin otro diseño que haya cambiado, tampoco lo dice."""
        stale = self.road_lines("es", self.facts(), state="stale", others=("des_psf_relleno",))
        line = stale[-1]
        self.assertTrue(line.alert)
        self.assertEqual(line.text, "Lee otro diseño de la versión que cambió, «des_psf_relleno»: recalcular la pista no la asienta si ese diseño se apoya ya en ella. "
                                    "Rehaga la pista sobre la superficie de ese diseño o descártela")
        english = self.road_lines("en", self.facts(), state="stale", others=("des_psf_relleno", "des_psf_carga"))[-1].text
        self.assertIn("«des_psf_relleno», «des_psf_carga»", english)
        self.assertTrue(english.endswith("Redo the road on the surface of that design, or discard it"))
        self.road_lines("es", self.facts(), state="current", others=("des_psf_relleno",))
        self.assertFalse(self.called, "una pista al día no pregunta por otros diseños")
        self.assertNotIn("recalcular la pista no la asienta", " ".join(self.texts(self.road_lines("es", self.facts(), state="current", others=("des_psf_relleno",)))))
        self.assertNotIn("recalcular la pista no la asienta", " ".join(self.texts(self.road_lines("es", self.facts(), state="stale", others=()))))

    def test_b_b_a_marked_layer_says_so_and_why(self) -> None:
        """T26-b: si la capa de ejes de pistas está marcada para la pista, la barra N lo dice, en alerta: todavía dice lo de antes (el estado, el perfil o la clase) **porque lo que cambió (el valor de un perfil) no la pone al
        día al instante**, y qué la pone al día; sin la marca, no."""
        marked = self.road_lines("es", self.facts(), state="stale", marked=True)[-1]
        self.assertTrue(marked.alert)
        self.assertEqual(marked.text, "La capa de ejes de pistas para QGIS está marcada: todavía dice lo que esta pista era antes (su estado, su perfil o su clase), porque un cambio como el valor de un "
                                      "perfil no la pone al día al instante; la próxima orden de pistas o «Recalcular lo obsoleto» sí")
        self.assertIn("«Recompute the stale results» does", self.road_lines("en", self.facts(), state="stale", marked=True)[-1].text)
        self.assertFalse(any("QGIS" in text for text in self.texts(self.road_lines("es", self.facts(), state="stale", marked=False))))

    def test_b_c_no_text_promises_that_a_field_of_the_proposed_layer_does_not_make_the_road_stale(self) -> None:
        """Decisión tras la T27: el hash de la capa propuesta cuenta todas sus columnas, así que **editar un campo también deja obsoleta la pista**; los textos nuevos de la barra N no prometen lo
        contrario («un campo no», «solo la geometría»…) ni hablan de campos, y todos están traducidos."""
        self.assertEqual(self.i18n.untranslated(list(NEW_MSGIDS)), [])
        for msgid in NEW_MSGIDS:
            for shown in (msgid, self.i18n.translate("es", msgid)):
                lower = shown.lower()
                self.assertNotIn("field", lower, msgid)
                self.assertNotIn("campo", lower, msgid)
                self.assertNotIn("only the geometry", lower)
                self.assertNotIn("solo la geometría", lower)

    # --- c: las listas de la accesibilidad ----------------------------------------------------------

    def access(self, language: str = "es", *, berms: int = 2, final: bool = True, nothing: bool = False) -> list:
        """Las líneas de la barra N de una accesibilidad con lo guardado a mano: ``berms`` tramos de berma (el primero comunicado), dos plataformas (una comunicada, con su lugar) y dos zonas (la
        comunicada, sin lugar, y la que no, con el que guarda su tabla)."""
        self.i18n.set_language(language)
        rows = tuple(self.road_card.BermRow(number, "des_brm_cantera", 100.0 + number, 400.0, number == 1, WEST + 10.0 * number, NORTH - 20.0) for number in range(1, berms + 1))
        platforms = (self.road_card.PlatformRow("PLT-001", "Carga", True, 131.0, self.road_card.AccessSpot(WEST + 30.0, NORTH - 30.0, 160.0)),
                     self.road_card.PlatformRow("PLT-002", "Taller", False, None, self.road_card.AccessSpot(WEST + 30.0, NORTH - 44.0, 80.0)))
        zones = (self.access_store.AccessZone("zona_de_la_balsa", True), self.access_store.AccessZone("zona_del_camino", False, WEST + 45.0, NORTH - 15.0, 18.5, 30.0),
                 self.access_store.AccessZone("zona_con_lugar", True, WEST + 5.0, NORTH - 5.0))  # una comunicada cuya tabla (editada fuera) guarda un lugar: tampoco lleva «Ir a»
        facts = self.road_card.AccessFacts("des_exp_cantera", "des_fin_cantera" if final else None, None if nothing else 100.5, None if nothing else 130.25, None if nothing else 1320.0,
                                           140.0 if final and not nothing else None, rows, platforms, zones, ())
        entry = SimpleNamespace(operation_uid="op", record=SimpleNamespace(state="current", code="ACC-001"))
        with mock.patch.object(self.road_card, "read_access_facts", return_value=facts):
            return self.panels._access_card_lines(None, None, SimpleNamespace(uid="v1", code="V01"), entry)

    def test_c_the_accessibility_lists_what_is_not_communicated_first_with_its_go_to(self) -> None:
        """RF-015-25, RF-017-25 (M4): la ficha de la accesibilidad enseña la superficie, las cotas mínima y máxima alcanzables con el área, la cota mínima sobre la final de su cantera y cuántos
        tramos de berma, plataformas y zonas quedan comunicados; y **las tres listas, comunicados o no**: **las que no, primero y en alerta**, cada una con su **«Ir a»** (``ROW_PLACE``, con el lugar y el
        radio de ``place_of``); la zona comunicada no guarda lugar y no lleva «Ir a»."""
        lines = self.access()
        texts = self.texts(lines)
        self.assertEqual(texts[:6], ["Accesibilidad", "Superficie: «des_exp_cantera»", f"Cotas alcanzables: de 100,50 a 130,25 m · {self.n(1320.0, 0)} m²",
                                     "Cota mínima alcanzable sobre la superficie final «des_fin_cantera» de la cantera: 140,00 m",
                                     "Comunicado · tramos de berma: 1 de 2 · plataformas: 1 de 2 · zonas «requiere acceso»: 2 de 3", "Tramos de berma (2)"])
        berm_rows = [line for line in lines if line.text.startswith("Tramo de berma")]
        self.assertEqual([line.text.split(" · ")[1] for line in berm_rows], ["no comunicado", "comunicado"], "las que no se comunican, antes")
        self.assertEqual([line.alert for line in berm_rows], [True, False])
        self.assertEqual({line.kind for line in berm_rows}, {self.panels.ROW_PLACE})
        place = self.constraint_panels.place_of(WEST + 20.0, NORTH - 20.0, 400.0)
        self.assertEqual(berm_rows[0].uid, ";".join(place), "el lugar y el radio de «Ir a»: los de place_of")
        self.assertEqual(self.texts(lines).count("Plataformas (2)"), 1)
        platforms = [line for line in lines if line.text.startswith("Plataforma «")]
        self.assertEqual([(line.text, line.alert, line.kind) for line in platforms],
                         [("Plataforma «Taller» (PLT-002): no comunicada", True, self.panels.ROW_PLACE),
                          ("Plataforma «Carga» (PLT-001): comunicada, se llega a la cota 131,00 m", False, self.panels.ROW_PLACE)])
        self.assertEqual(platforms[1].uid, ";".join(self.constraint_panels.place_of(WEST + 30.0, NORTH - 30.0, 160.0)))
        zones = [line for line in lines if line.text.startswith("Zona «")]
        self.assertEqual([(line.text, line.alert, line.kind) for line in zones],
                         [("Zona «zona_del_camino» que requiere acceso: no comunicada; lo alcanzable más próximo está a 18,50 m (diferencia de cota 30,00 m)", True, self.panels.ROW_PLACE),
                          ("Zona «zona_de_la_balsa» que requiere acceso: comunicada", False, self.panels.ROW_FIELD),
                          ("Zona «zona_con_lugar» que requiere acceso: comunicada", False, self.panels.ROW_FIELD)])
        self.assertEqual(zones[0].uid, ";".join(self.constraint_panels.place_of(WEST + 45.0, NORTH - 15.0, 0.0)), "el lugar que guarda la tabla de la zona sin comunicar")
        self.assertEqual((zones[1].uid, zones[2].uid), ("", ""), "la zona comunicada no guarda lugar y, aunque su tabla lo lleve, no tiene «Ir a»")
        english = self.texts(self.access("en"))
        self.assertEqual(self.n(1320.0, 0), "1,320")
        self.assertIn("Communicated · berm stretches: 1 of 2 · platforms: 1 of 2 · zones that require access: 2 of 3", english)
        self.assertIn("Reachable elevations: from 100.50 to 130.25 m · 1,320 m²", english)
        self.assertFalse(any("{" in shown for shown in (*texts, *english)))

    def test_c_b_nothing_reachable_no_final_and_a_long_list(self) -> None:
        """RF-017-24, RF-017-25: sin nada alcanzable lo dice en alerta (y no da cotas); sin cantera no hay cota sobre la final; una lista de más de ``LIST_LIMIT`` filas enseña las primeras —las que no
        se comunican, antes— y una nota con cuántas faltan; sin filas, «Nada que enseñar»."""
        nothing = self.access(nothing=True)
        self.assertIn(("No se alcanza nada desde los puntos de entrada", True), [(line.text, line.alert) for line in nothing])
        self.assertFalse(any(line.text.startswith("Cotas alcanzables") for line in nothing))
        self.assertFalse(any("superficie final" in line.text for line in self.access(final=False)))
        limit = self.panels.LIST_LIMIT
        long = self.access(berms=limit + 5)
        berm_rows = [line for line in long if line.text.startswith("Tramo de berma")]
        self.assertEqual(len(berm_rows), limit)
        self.assertTrue(all(line.alert for line in berm_rows), "caben las que no se comunican y no la que sí")
        self.assertIn(f"… y 5 más (la lista entera está en las tablas de la accesibilidad)", self.texts(long))
        empty = self.panels._access_list_lines("Tramos de berma", [])
        self.assertEqual([(line.kind, line.text) for line in empty], [(self.panels.ROW_HEADING, "Tramos de berma (0)"), (self.panels.ROW_NONE, "Nada que enseñar")])

    def test_c_c_without_a_stored_result_it_says_so_and_does_not_invent_figures(self) -> None:
        """RF-015-25: una accesibilidad cuyo resultado ya no está en el proyecto (ni el informe ni las tablas) lo dice; sin versión, no hay nada que leer."""
        self.i18n.set_language("es")
        entry = SimpleNamespace(operation_uid="op", record=SimpleNamespace(state="current", code="ACC-001"))
        with mock.patch.object(self.road_card, "read_access_facts", return_value=None):
            lines = self.panels._access_card_lines(None, None, SimpleNamespace(uid="v1", code="V01"), entry)
        self.assertEqual(self.texts(lines), ["Accesibilidad", "El proyecto no tiene el resultado de esta accesibilidad"])
        self.assertEqual(self.panels._access_card_lines(None, None, None, entry), [])

    # --- d: el dibujo --------------------------------------------------------------------------------

    def drawn(self, rows: list) -> FakeLayout:
        self.i18n.set_language("es")
        shown = SimpleNamespace(item_uid="u1", item_found=True, item_title="Lo alcanzable por las pistas · Alcanzable",
                                item=[SimpleNamespace(kind=line.kind, name=line.text, alert=line.alert, uid=line.uid) for line in rows])
        layout = FakeLayout()
        self.assertTrue(self.panels._draw_item(layout, shown, "u1", 400.0))
        return layout

    def test_d_a_row_with_a_place_draws_its_go_to_button_and_one_without_it_does_not(self) -> None:
        """RF-017-25 (M4): en la barra N cada fila con lugar dibuja su texto (en alerta si no se comunica) y **un botón «Ir a» (``geoblender.core_go_to_place``) con la ``x``, la ``y`` y el radio** de su
        lugar; la fila sin lugar (la zona comunicada) no dibuja botón; un lugar que no se lee no lo dibuja."""
        lines = self.access()
        layout = self.drawn([*lines, self.panels.CardLine(self.panels.ROW_PLACE, "Una con el lugar roto", uid="1;2")])
        buttons = layout.of_kind("operator")
        self.assertEqual({button.target for button in buttons}, {self.constraint_panels.GO_TO_PLACE})
        self.assertEqual({button.text for button in buttons}, {"Ir a"})
        with_place = [line for line in lines if line.kind == self.panels.ROW_PLACE]
        self.assertEqual(len(buttons), len(with_place), "un botón por fila con lugar: ni uno más, ni uno menos")
        self.assertEqual([(button.properties.x, button.properties.y, button.properties.radius) for button in buttons], [tuple(line.uid.split(";")) for line in with_place])
        shown = layout.texts()
        self.assertIn("Zona «zona_de_la_balsa» que requiere acceso: comunicada", shown)
        self.assertIn("Una con el lugar roto", shown)
        alerts = {item.text for item in layout.of_kind("label") if item.alert}
        self.assertTrue(any("no comunicada" in text for text in alerts), "las que no se comunican, en alerta")

    # --- z: el registro --------------------------------------------------------------------------------

    def test_z_disabling_geoblender_leaves_blender_as_it_was(self) -> None:
        """Principio 8 (``geoblender/AGENTS.md``, Registro): con la barra N de la pista y de la accesibilidad, desactivar Geoblender quita la barra y las líneas del objeto y la huella entera de
        Blender vuelve a la del principio de la sesión."""
        self.addCleanup(blender_ext.enable)  # las demás pruebas de la clase, habilitada
        blender_ext.disable()
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


if __name__ == "__main__":
    unittest.main()
