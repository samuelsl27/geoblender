# SPDX-License-Identifier: GPL-3.0-or-later
"""La corta por bancos frente a su documentación (spec 018, T37; plan 018 §5.6; definición de hecho §3.7).

Como las de las pistas (``test_design_docs.RoadsGuideDocTest``), estas pruebas avisan de que el código y la documentación se
separan. Sin la carpeta de la documentación se omiten (recurso ``docs``):

- la guía de uso ``docs/usuario/corta-por-bancos.md``: todo texto entre «» sale del catálogo o es un ejemplo que esta prueba lista;
  las órdenes llevan el texto de su catálogo; las cifras, los tipos y los valores por defecto de su tabla son los del código;
  los recuentos, los datos del anexo y el estado del recuadro del principio son ciertos; y el cuerpo no lleva jerga de desarrollo;
- el glosario (las cinco entradas nuevas y «Rampa»), ``formato-proyecto.md`` (§3.3 y §3.11: las familias de la corta), la barra
  superior (§8.7), los paneles contextuales (§3.11) y la ficha ``des.md`` (§2, §4.5.1, §4.6, «Datos que posee» y el estado);
- las trampas T-1 a T-3 del plan, el índice de specs, el roadmap, el ``README.md`` y el ``CHANGELOG.md`` del código.
"""

from __future__ import annotations

import re
import unittest

from tests.support import docs
from tests.support.bs_tables import backticked, section, tables
from tests.support.package import import_geoblender
from tests.support.repo import ROOT
from tests.unit.design.test_design_docs import (
    DEFAULT_TEXT, NO_DEFAULT, UNIT_TEXT, inline_tokens, keyed_rows, one_line, quotes, shared_quote_index, spanish_number)

design = import_geoblender("design")
dparams = import_geoblender("design.params")
dprov = import_geoblender("design.provenance")
catalog = import_geoblender("core.catalog")
pit_rose = import_geoblender("design.pit_rose")
pit_ramp_def = import_geoblender("design.pit_ramp_def")

GUIDE_RELPATH = "docs/usuario/corta-por-bancos.md"
DES_RELPATH = "docs/arquitectura/modulos/des.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
BS_RELPATH = docs.BS_RELPATH
PC_RELPATH = "docs/arquitectura/interfaz/paneles-contextuales.md"
GLOSSARY_RELPATH = "docs/producto/glosario.md"
TRAPS_RELPATH = "docs/trampas.md"
README_RELPATH = "README.md"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
ANNEX_HEADING = "## Anexo. Para quien mantiene el código"

# Las órdenes de la corta (con las dos que la guía usa de otras specs) y las provisionales de R-35 que ya no existen.
PIT_ORDERS = ("geoblender.des_create_pit", "geoblender.des_expand_bench", "geoblender.des_edit_pit_ramp", "geoblender.des_edit_pit_rose",
              "geoblender.des_pit_skyline", "geoblender.des_pit_surface")
OTHER_ORDERS = ("geoblender.des_edit_bench_profiles", "geoblender.des_edit_road_profile")
GONE_COMMANDS = ("des_new_pit", "des_add_ramp", "des_compute_daylight", "des_create_design_surface")
CLASSES = {"des_create_pit": "GEOBLENDER_OT_des_create_pit", "des_expand_bench": "GEOBLENDER_OT_des_expand_bench",
           "des_edit_pit_ramp": "GEOBLENDER_OT_des_edit_pit_ramp", "des_edit_pit_rose": "GEOBLENDER_OT_des_edit_pit_rose",
           "des_pit_skyline": "GEOBLENDER_OT_des_pit_skyline", "des_pit_surface": "GEOBLENDER_OT_des_pit_surface"}

# De lo que la guía pone entre «», lo que no está en el catálogo: un ejemplo o un término que la propia guía explica. La prueba exige que
# siga en la guía y que no haya ninguno más.
PIT_EXAMPLES: tuple[str, ...] = (
    "polilínea", "cadena", "cumple",
    # El objeto del TIN se llama como la corta (T40e, H3-6): el nombre de la corta del ejemplo no es del catálogo.
    "TIN de la corta Corta E1 · V01",
)

# Los valores de la tabla de §12 de la guía: cada uno con su familia en el código.
PIT_TABLE_VALUES = ("top_level_m", "bottom_level_m", "max_benches", "min_floor_width_m", "n_berm", "corner",
                    "arc_tol_m", "simplify_m", "close_radius_m", "az_window_m")
RAMP_TABLE_VALUES = ("gradient_pct", "transition_m", "turn_radius_m", "min_platform_m")
JARGON = re.compile(r"\bT\d{2}b?\b|\bH3\b|\bCE-\d|\bRNF-\d|\bRF-\d|\bDIFF-|check\.py|paso `hito`|des_(?:psf|epr|prp|pbl|psk|prl|pfn|pbk)_|design\.|gis\.offset"
                    r"|worker|DS-\d|pit_limits|ramp_names")

NEW_GLOSSARY = {"Polilínea de diseño": "design_polyline", "Azimut de la cara": "face_azimuth", "Banco doble": "double_bench",
                "Roseta de taludes de diseño": "design_rose", "Definición de rampa": "ramp_definition"}
PIT_FAMILIES_DOC = ("des.pit.{e}.*", "des.rose.{r}.{i}.*", "des.pitramp.{q}.*")
PIT_MODULES_46 = ("gis.offset", "design.pit_offset", "design.pit_bench", "design.pit_ramp", "design.pit_surface", "design.pit_sky")
OLD_46 = ("design.vector.DesignString", "design.vector.variable_offset", "design.vector.design_upward", "design.vector.Ramp",
          "design.vector.from_shell", "design.vector.daylight", "design.vector.toes_crests", "design.minplus.stepped_cone_envelope",
          "design.rasterize.to_grid")
LAST_TASK = "T37"
TRAPS = ("el desfase con dos puntos por esquina duplica los vértices en cada pasada", "la regla de la vuelta con un solo lado rompe anillos",
         "una CDT de contornos anidados rellena la envolvente convexa")


def guide_family(pattern: str) -> object:
    for family in (*dparams.PIT_FAMILIES, *dparams.PITRAMP_FAMILIES):
        if family.pattern.rsplit(".", 1)[1] == pattern:
            return family
    raise KeyError(pattern)


@docs.requires_docs
class PitGuideDocTest(unittest.TestCase):
    """La guía de uso de la corta por bancos dice lo que el código hace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = docs.read(GUIDE_RELPATH)
        cls.index = shared_quote_index()

    def guide_section(self, heading: str) -> str:
        """La sección ``heading`` de la guía en una línea y sin las marcas «> » de sus recuadros."""
        return one_line(re.sub(r"(?m)^> ?", "", section(self.guide, heading)))

    def assert_told(self, heading: str, facts: tuple[str, ...]) -> None:
        text = self.guide_section(heading)
        for fact in facts:
            with self.subTest(section=heading[:5], fact=fact):
                self.assertIn(fact, text)

    def test_every_quoted_text_is_in_the_catalog_or_is_a_listed_example(self) -> None:
        """Principio 10, RF-018-34 (T37): todo texto de la guía entre «» sale del catálogo o está en :data:`PIT_EXAMPLES`, y todo lo de la lista sigue en la guía."""
        found = quotes(self.guide)
        self.assertGreater(len(found), 8)
        unknown = sorted({quote for quote in found if quote not in PIT_EXAMPLES and not self.index.has(quote)})
        self.assertEqual(unknown, [], "textos de la guía que el catálogo no dice (cámbielos en la guía, o en el código si es él el que está mal)")
        self.assertEqual(sorted(set(PIT_EXAMPLES) - set(found)), [], "ejemplos que la guía ya no cita: quítelos de PIT_EXAMPLES")

    def test_every_listed_example_is_not_in_the_catalog(self) -> None:
        """Un ejemplo de :data:`PIT_EXAMPLES` que sí está en el catálogo sobra."""
        for example in PIT_EXAMPLES:
            with self.subTest(example=example):
                self.assertFalse(self.index.has(example))

    def test_orders_are_named_with_their_catalog_text(self) -> None:
        """RF-018-34, D-20 (T37): la guía nombra cada orden de la corta y las dos de otras specs que usa con el texto de su catálogo, dice dónde están
        (**Diseño ▸ Corta por bancos**) y las provisionales de R-35 ya no existen."""
        cat = catalog.load()
        for key in (*PIT_ORDERS, *OTHER_ORDERS):
            with self.subTest(order=key):
                self.assertIn(cat.commands[key].label_es, self.guide)
        self.assertIn("Diseño ▸ Corta por bancos", self.guide)
        for gone in GONE_COMMANDS:
            with self.subTest(gone=gone):
                self.assertNotIn(f"geoblender.{gone}", cat.commands)

    def test_the_values_their_types_and_defaults_are_the_code_s(self) -> None:
        """RF-018-08, RF-018-10, RF-018-13, RF-018-15, RF-018-17 (D-8, D-14, D-19; T37): la tabla de §12 da de cada valor su unidad, su tipo (ADOPTADO o
        HIPÓTESIS) y su valor por defecto **como los declara el código**: las cuatro tolerancias del desfase y las dos del zig-zag, HIPÓTESIS sin valor; los
        criterios de parada, sin valor; solo ``n_berm`` (1) y ``corner`` (``round``) lo tienen."""
        rows = keyed_rows(section(self.guide, "## 12. Las cifras y su tipo"))
        for key in (*PIT_TABLE_VALUES, *RAMP_TABLE_VALUES):
            template = guide_family(key).template  # type: ignore[attr-defined]
            with self.subTest(value=key):
                self.assertIn(key, rows)
                cells = rows[key]
                self.assertEqual(cells[1], UNIT_TEXT[template.unit])
                self.assertEqual(cells[2], template.kind.value)
                if template.default is None:
                    expected = NO_DEFAULT
                elif isinstance(template.default, str):
                    expected = DEFAULT_TEXT.get(key) or template.default
                else:
                    expected = spanish_number(template.default)
                self.assertEqual(cells[3], expected)
        self.assertEqual({family.pattern.rsplit(".", 1)[1] for family in dparams.PIT_FAMILIES if family.template.default is not None},
                         {"n_berm", "corner", "discarded"})
        self.assertEqual({k for k in (*PIT_TABLE_VALUES, *RAMP_TABLE_VALUES) if guide_family(k).template.kind.value == "HIPÓTESIS"},  # type: ignore[attr-defined]
                         {"arc_tol_m", "simplify_m", "close_radius_m", "az_window_m", "turn_radius_m", "min_platform_m"})

    def test_the_counts_the_guide_says_are_the_code_s(self) -> None:
        """RF-018-31 (T37): las **21 cifras** de la corta y, en el anexo, los **23 valores** de la entidad son los del código, y las seis órdenes, las de su menú."""
        self.assertEqual(len(dprov.PIT_FIGURES), 21)
        self.assertEqual(len(list(dparams.PitParam)), 23)
        self.assertIn("**21 cifras**", self.guide_section("## 7. Calcular, confirmar y crear"))
        self.assertIn("23 valores", self.guide_section(ANNEX_HEADING))
        self.assertIn("(21)", self.guide_section(ANNEX_HEADING))
        self.assertEqual(len(PIT_ORDERS), 6)

    def test_the_body_of_the_guide_has_no_development_jargon(self) -> None:
        """Definición de hecho §3.7 (T37): la guía la lee un ingeniero de minas: ni el principio ni el cuerpo hasta el anexo llevan el nombre de una tarea, de un criterio o de
        un requisito, ``check.py``, un módulo, un papel ni el decorado de una tabla (``des_pbl_``…); todo eso va **al anexo**, que existe y dice dónde está cada dato. Las tres
        capas que se ven en QGIS sí se nombran."""
        end = self.guide.index(ANNEX_HEADING)
        body = self.guide[:end]
        found = sorted({match.group(0) for match in JARGON.finditer(body)})
        self.assertEqual(found, [], "jerga de desarrollo en el cuerpo de la guía: va al anexo")
        for layer in ("des_pit_<vNN>", "des_sky_<vNN>", "des_pxb_<nombre>_<vNN>"):
            with self.subTest(layer=layer):
                self.assertIn(layer, body)
        self.assertGreater(len(self.guide[end:]), 1200)

    def test_data_paths_parameters_and_operations_are_the_code_s(self) -> None:
        """RF-018-01, RF-018-31, RF-018-33 (plan 018 §5.2; T37): el anexo da la ruta de cada dato de la corta (los seis con nombre y las dos capas por versión), las dos tablas de
        proyecto, las tres familias de parámetros, los tipos de operación y dice cuál es la única capa que se edita en QGIS."""
        text = self.guide_section(ANNEX_HEADING)
        where = inline_tokens(section(self.guide, ANNEX_HEADING))
        self.assertEqual(len(dprov.PIT_DATA_FAMILIES), 8)
        for family in dprov.PIT_DATA_FAMILIES:
            shown = dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01").replace("mi_nombre", "<nombre>").replace("v01", "<vNN>")
            with self.subTest(dataset=family.code):
                self.assertTrue(any(shown in token for token in where), shown)
        for name in (pit_rose.TABLE, pit_ramp_def.TABLE, *PIT_FAMILIES_DOC):
            with self.subTest(name=name):
                self.assertIn(name, where)
        for op in (*dprov.PIT_VERSION_TYPES, dprov.EDIT_PIT_ROSES, dprov.EDIT_PIT_RAMPS):
            with self.subTest(operation=op):
                self.assertIn(op, where)
        self.assertEqual([family.code for family in dprov.PIT_DATA_FAMILIES if family.qgis_editable], ["pxb"])
        self.assertIn("la **única que se edita en QGIS**", self.guide_section("## 10. Lo que se ve y lo que se entrega"))
        self.assertIn("des.pit_*", text)

    def test_the_head_says_it_is_in_main_unseen_and_pending_review(self) -> None:
        """Definición de hecho §3.7 (T37 y T42): el recuadro dice, sin jerga, que la 018 está **cerrada** (Samuel, 25/11/2026; spec 0.14) y en `main`, que se probó **sin pantalla**,
        que el contraste con el proyecto de referencia **no concluyó**, que lo que no se vio en pantalla sigue abierto y que la guía está **pendiente de la revisión de Samuel**; y
        lleva su fecha y su spec."""
        head = one_line(re.sub(r"(?m)^> ?", "", self.guide[:self.guide.index("## 1. Las palabras")]))
        for fact in ("**Fecha:** 24/11/2026", "**Spec:** 018", "**cerrada** (Samuel, 25/11/2026; spec 0.14)", "en `main`", "**sin pantalla**", "**Queda abierto:**",
                     "**no concluyó**", "lo que no se vio en pantalla", "**pendiente de la revisión de Samuel**"):
            with self.subTest(head=fact):
                self.assertIn(fact, head)
        for stale in ("cerrada y publicada", "sin cerrar", "Aún no se ha visto en pantalla", "verificación única", "Silvestre"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head)
        self.assertIsNone(JARGON.search(head))

    def test_the_words_and_the_scenarios_are_told(self) -> None:
        """RF-018-07, RF-018-08, RF-018-15 (spec §4, §2; T37): §1 define la polilínea de diseño, el banco y el banco doble, el azimut de la cara (que no es el rumbo geológico),
        la roseta, la definición de rampa, la línea de cielo, el recinto y el hallazgo; §2 recorre E1 a E5 y §3 dice qué hay que tener antes y qué se rechaza."""
        self.assert_told("## 1. Las palabras", ("**Polilínea de diseño**", "**Banco**", "**banco doble**", "**Azimut de la cara**", "No es el rumbo geológico",
                                                 "baja", "**Roseta de taludes de diseño**", "sin huecos ni solapes", "**Definición de rampa**", "**Línea de cielo**",
                                                 "**Recinto**", "**Hallazgo**"))
        two = self.guide_section("## 2. El trabajo de un vistazo")
        for scenario in ("E1", "E2", "E3", "E4", "E5"):
            with self.subTest(scenario=scenario):
                self.assertIn(f"| {scenario} ·", two)
        self.assert_told("## 3. Antes de empezar", (
            "**versión activa que se pueda editar**", "Las capas solo se leen y nunca se modifican", "la misma altura y la misma cota de ancla",
            "la búsqueda de intocables", "se rechaza antes de escribir nada", "un polígono con huecos", "más de 200 bancos", "50.000 vértices"))

    def test_the_modes_the_stop_criteria_and_the_offset_are_told(self) -> None:
        """RF-018-02, RF-018-10, RF-018-11 a 14 (T37): §4 dice los dos modos, los tres criterios de parada (sin valor por defecto, el primero que se cumpla, al menos uno), el
        primer banco de altura variable, lo que dice la orden cuando no sale a superficie o queda vacía (sin relajar nada) y cómo se hace el desfase: arcos circunscritos,
        verificado y rechazado con el banco, el lugar y el defecto."""
        self.assert_told("## 4. Nueva corta…", (
            "**Ascendente**", "**Descendente**", "cota de coronación", "**ancho mínimo del fondo**", "**cota de fondo**", "**número máximo de bancos**", "sin valor por defecto",
            "en el primero que se cumpla", "al menos uno", "el **primer banco tiene altura variable**", "más de 50 partes", "no relaja ningún valor por su cuenta",
            "arcos circunscritos", "**verifica**", "el banco, el lugar y el defecto", "nunca queda un resultado dudoso en silencio", "**Calcular** enseña", "una sola transacción"))

    def test_sectors_roses_and_double_benches_are_told(self) -> None:
        """RF-018-06 a 09 (T37): §5 dice el perfil base y el de cada sector, el sector del punto medio, la roseta, los bancos por berma (1 por defecto, uno solo para toda la corta) y
        que una fase es un sector con nombre."""
        self.assert_told("## 5. Perfiles, roseta, sectores y bancos dobles", (
            "**perfil base**", "el sector que contiene su punto medio", "se parte donde cruza el límite de dos sectores", "ventana de longitud", "1 por defecto",
            "Es un único *n* para toda la corta", "todavía no se mezclan", "Una **fase** es, por ahora, un sector con nombre"))

    def test_the_ramps_are_told(self) -> None:
        """RF-018-15 a 21 (T37): §6 dice los dos tipos, lo que cabe, la descendente por la cresta, las reglas de la 017 (el radio, la pendiente media con su confirmación y su
        motivo, lo que se rechaza sin cambiar nada) y que ninguna orden relaja una cifra."""
        self.assert_told("## 6. Rampas", (
            "**Espiral**", "**Zig-zag**", "más la berma", "se prolonga más allá de ese lado", "**avisa**", "**baja por la cresta**", "no se repiten", "se rechaza la rampa",
            "**no se crea sin su confirmación expresa y un motivo**", "con quién y cuándo", "otro tipo, otro sentido u otro inicio", "**sin cambiarlos**",
            "Ninguna orden cambia la pendiente"))

    def test_calculate_create_findings_and_the_restrictions_are_told(self) -> None:
        """RF-018-05, RF-018-26, RF-018-27, RF-018-31, RF-015-12 (T37): §7 dice que Calcular no escribe, lo que da Crear, Esc, las cifras, los hallazgos (un banco sin perfil no es un
        «cumple»), los avisos y que la corta no declara restricciones y no mueve nada fuera del perímetro."""
        self.assert_told("## 7. Calcular, confirmar y crear", (
            "**Calcular** no escribe nada", "**Crear** registra la corta", "**Esc** lo cancela sin dejar nada a medias", "volumen por banco", "un banco sin perfil",
            "un hallazgo y no un «cumple»", "más de una altura de banco", "no impide crearla", "**no declara ninguna restricción**", "su zona se excava, no se protege",
            "no mueve nada fuera del perímetro de actuación"))

    def test_assisted_editing_the_skyline_and_the_surface_are_told(self) -> None:
        """RF-018-22 a 24, RF-018-28 a 30 (T37): §8 y §9 dicen que «Expandir banco…» no escribe hasta confirmar y deja una capa editable, los bancos fijados (tal cual, con su cota,
        nunca se mueve una línea), que la línea de cielo no es una restricción, que la rejilla es la superficie oficial, y el TIN y el sólido como vistas con el aviso de 300.000
        triángulos, GeoTIFF y CSV."""
        self.assert_told("## 8. Edición asistida: Expandir banco… y bancos fijados", (
            "sin escribir nada", "capa de líneas con Z que se edita en QGIS", "sin tocar ninguna superficie", "no sobrescribe lo que usted dibujó", "**tal cual**",
            "con el banco y las dos cotas", "Nunca se mueve una línea suya"))
        self.assert_told("## 9. La línea de cielo, la superficie y el sólido", (
            "No es una restricción", "es la **rejilla del proyecto**: la oficial", "**vistas** que se regeneran", "sin sacar de ellos ninguna cifra", "300.000 triángulos",
            "**GeoTIFF**", "**CSV**"))

    def test_what_it_does_not_do_yet_says_what_the_code_does_not_do(self) -> None:
        """Definición de hecho §3.7 (T37): §13 dice lo que hoy no hace —no parte de la concha, no admite polígonos con huecos, no mezcla *n* distintos, la rampa de la descendente con
        bancos dobles, con varios límites o sobre el primer banco variable— y lo medido, con las cifras de T36 (20 y 5 bancos; 115.000 y 160.000 puntos; +27 s)."""
        self.assert_told("## 13. Lo que no hace todavía", (
            "No parte de la concha óptima", "R-49", "R-55", "No admite polígonos con huecos", "bancos por berma distintos", "bancos dobles", "varios límites con rampa",
            "primer banco de altura variable", "20 bancos en espiral y 5 en zig-zag", "115.000 puntos", "160.000 puntos", "0,33 s", "27 s", "No se ha visto en pantalla"))
        self.assertEqual(dparams.PitParam.N_BERM.value, "n_berm")


@docs.requires_docs
class PitGlossaryDocTest(unittest.TestCase):
    """El glosario dice las palabras de la corta."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(GLOSSARY_RELPATH)
        cls.rows = {cells[0]: cells for table in tables(section(cls.text, "## 9. Diseño de explotación")) for cells in table}

    def test_the_five_new_entries_exist_with_their_identifier(self) -> None:
        """Plan 018 §5.6 (T37): «Polilínea de diseño», «Azimut de la cara», «Banco doble», «Roseta de taludes de diseño» y «Definición de rampa» están en §9, cada una con su
        identificador en inglés y su spec."""
        for term, identifier in NEW_GLOSSARY.items():
            with self.subTest(term=term):
                self.assertIn(term, self.rows)
                cells = self.rows[term]
                self.assertEqual(backticked(cells[1]), [identifier])
                self.assertIn("Spec 018", cells[3] if len(cells) > 3 else cells[2])

    def test_the_azimuth_is_not_the_geological_strike_and_the_polyline_is_not_a_chain(self) -> None:
        """RF-018-07, D-16 (T37): el azimut de la cara es hacia donde baja y no es el rumbo geológico; la polilínea de diseño no es la cadena de las entidades."""
        azimuth = " ".join(self.rows["Azimut de la cara"])
        self.assertIn("baja", azimuth)
        self.assertIn("rumbo geológico", azimuth)
        self.assertIn("cadena", " ".join(self.rows["Polilínea de diseño"]))

    def test_the_ramp_points_to_this_spec_and_not_to_r35(self) -> None:
        """Plan 018 §5.6 (T37): «Rampa» apunta a la spec 018 para la espiral y el zig-zag, y ya no dice que sean de R-35."""
        ramp = " ".join(self.rows["Rampa"])
        self.assertIn("Spec 018", ramp)
        self.assertNotIn("son de R-35", ramp)
        self.assertIn("Spec 018", " ".join(self.rows["Línea de cielo"]))


@docs.requires_docs
class PitFormatAndInterfaceDocTest(unittest.TestCase):
    """``formato-proyecto.md``, la barra superior y los paneles contextuales dicen la corta."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.format = docs.read(FORMAT_RELPATH)
        cls.bs = docs.read(BS_RELPATH)
        cls.pc = docs.read(PC_RELPATH)

    def test_the_families_of_data_are_in_the_tables_of_the_modules(self) -> None:
        """RF-018-01, RF-018-31, RF-018-33 (plan 018 §5.2.3; T37): §3.11 nombra cada familia de datos de la corta (``des_pbl_``, ``des_psk_``, ``des_prl_``, ``des_pfn_``, ``des_pbk_``,
        ``des_pxb_``), las dos capas por versión y las dos tablas de proyecto, con su operación."""
        named = inline_tokens(section(self.format, "### 3.11 Tablas de los módulos"))
        for family in dprov.PIT_DATA_FAMILIES:
            shown = dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01").replace("mi_nombre", "<nombre>").replace("v01", "<vNN>")
            with self.subTest(dataset=family.code):
                self.assertIn(shown, named)
        for table in (pit_rose.TABLE, pit_ramp_def.TABLE):
            with self.subTest(table=table):
                self.assertIn(table, named)
        for op in (*dprov.PIT_VERSION_TYPES, dprov.EDIT_PIT_ROSES, dprov.EDIT_PIT_RAMPS):
            with self.subTest(operation=op):
                self.assertIn(op, named)

    def test_the_families_of_parameters_are_in_the_parameter_section(self) -> None:
        """RF-018-07, RF-018-15 (plan 018 §5.2.2; T37): §3.3 nombra las tres familias de parámetros (la corta, la roseta y la definición de rampa), cuántos valores tiene cada una y
        que solo ``n_berm`` y ``corner`` tienen valor por defecto."""
        parameters = section(self.format, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados")
        named = inline_tokens(parameters)
        for pattern in PIT_FAMILIES_DOC:
            with self.subTest(family=pattern):
                self.assertIn(pattern, named)
        text = one_line(parameters)
        self.assertEqual(len(list(dparams.PitParam)), 23)
        for fact in ("23 valores", "(`n_berm`, 1; `corner`, `round`)", "Las cuatro tolerancias del desfase", "HIPÓTESIS"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_top_bar_lists_the_orders_with_their_catalog_label_and_real_class(self) -> None:
        """RF-018-34, D-20 (T37): §8.7 tiene la fila de cada orden de la corta con **el texto de su catálogo** y su clave, la clase real de cada una, y dice que las cuatro provisionales
        de R-35 ya no existen."""
        cat = catalog.load()
        section_text = section(self.bs, "## 8.7") if "## 8.7" in self.bs else self.bs
        lines = [line for line in self.bs.splitlines() if line.startswith("| ")]
        for key in PIT_ORDERS:
            short = key.removeprefix("geoblender.")
            label = cat.commands[key].label_es
            with self.subTest(order=short):
                self.assertTrue(any(line.startswith(f"| ↳ {label} | `{short}` |") for line in lines), label)
                self.assertIn(CLASSES[short], self.bs)
        for gone in GONE_COMMANDS:
            with self.subTest(gone=gone):
                self.assertIn(gone, section_text)
        self.assertIn("Desde la spec 018", self.bs)

    def test_the_card_of_an_entity_has_the_pit(self) -> None:
        """RF-018-26, RF-015-25 (T37): §3.11 de los paneles contextuales dice lo propio de una corta en «Entidad ▾» y en la barra N (sus cifras, el criterio que la paró, cada banco, los
        hallazgos con «Ir a», las rampas) y su entrada 018 con la guía de uso."""
        card = one_line(section(self.pc, "### 3.11 Entidad de diseño (`DESIGN_ENTITY`) — plataforma, acopio, contrafuerte, balsa, canal, pista"))
        for fact in ("018 (", "una **corta por bancos**", "el criterio que la paró", "cada banco con su volumen", "hallazgos", "`docs/usuario/corta-por-bancos.md`",
                     "su vista previa", "Línea de cielo…"):
            with self.subTest(fact=fact):
                self.assertIn(fact, card)


@docs.requires_docs
class PitCardDocTest(unittest.TestCase):
    """``modulos/des.md`` (§2, §4.5.1, §4.6, «Datos que posee» y el estado) dice la corta tal como es."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(DES_RELPATH)

    def test_section_2_names_the_real_modules_and_what_exists(self) -> None:
        """Plan 018 §5.6 (T37): §2 nombra los módulos reales del motor vectorial (el desfase de ``gis.offset``, los de ``design.pit_*``) y dice lo que ya existe de la rampa vectorial, sin
        decir que la rampa paramétrica, el espiral y el zig-zag «siguen sin código»."""
        two = one_line(section(self.text, "## 2. Motor vectorial: diseño clásico de corta desde la concha"))
        for name in PIT_MODULES_46:
            with self.subTest(module=name):
                self.assertIn(f"`{name}`", two)
        self.assertNotIn("siguen sin código", two)
        self.assertIn("Lo que ya existe** (spec 018", two)

    def test_section_46_has_no_stale_names_and_points_to_the_real_ones(self) -> None:
        """Plan 018 §5.6 (T37): §4.6 ya no prevé ``design.vector.*``, ``design.minplus`` ni ``design.rasterize``: dice dónde están los reales (§4.5.1)."""
        six = section(self.text, "### 4.6 API prevista (otras entradas del roadmap)")
        for old in OLD_46:
            with self.subTest(old=old):
                self.assertNotIn(f"`{old}", six)
        for name in ("design.pit_offset", "design.pit_surface", "gis.offset", "design.pit_store"):
            with self.subTest(real=name):
                self.assertIn(name, six)

    def test_section_451_is_complete_and_names_the_owned_data(self) -> None:
        """RF-018-01, RF-018-31, RF-018-33 (T37): §4.5.1 ya no dice «en curso», y «Datos que posee» nombra los datos de la corta, sus tres familias de parámetros, sus 21 cifras y sus
        operaciones."""
        self.assertIn("### 4.5.1 Lo que entrega la spec 018 (R-35)\n", self.text)
        self.assertNotIn("en curso: lo hecho hasta T04", self.text)
        owned = inline_tokens(section(self.text, "## Datos que posee"))
        for family in dprov.PIT_DATA_FAMILIES:
            shown = (dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01").replace("mi_nombre", "<nombre>").replace("v01", "<vNN>"))
            with self.subTest(dataset=family.code):
                self.assertIn(shown, owned)
        for pattern in (*PIT_FAMILIES_DOC, pit_rose.TABLE, pit_ramp_def.TABLE, *dprov.PIT_VERSION_TYPES, dprov.EDIT_PIT_ROSES, dprov.EDIT_PIT_RAMPS):
            with self.subTest(name=pattern):
                self.assertIn(pattern, owned)
        for figure in dprov.PIT_FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, owned)

    def test_the_state_of_the_018_is_said_in_the_head_and_the_table(self) -> None:
        """Definición de hecho §3.7 (T37): la cabecera y la fila de «Specs y entradas» dicen lo mismo: la 018, **cerrada** por Samuel el 25/11/2026 (0.14), en `main`, con las tareas de la T01 a la T37,
        la guía de uso y lo abierto al cierre (T42); y la fila antigua «Corta por bancos (R-35)» ya no está."""
        head = one_line(self.text[:self.text.index("## Responsabilidad")])
        row = re.search(r"^\| 018-des-corta-por-bancos .*$", self.text, re.MULTILINE)
        self.assertIsNotNone(row)
        assert row is not None
        for name, text in (("cabecera", head), ("fila de la tabla", row.group(0))):
            with self.subTest(place=name):
                for fact in ("de la T01 a la T37", "`docs/usuario/corta-por-bancos.md`"):
                    self.assertIn(fact, text)
        self.assertIn("**cerrada** por Samuel el 25/11/2026 (0.14", head)  # la cabecera no puede decir «a falta de publicar»: la prueba de la 017 lo prohíbe en ella
        self.assertIn("`verificacion.md` §7", head)
        self.assertIn("**cerrada** el 25/11/2026", row.group(0))
        for stale in ("aún no publicada ni cerrada", "sin publicar y sin cerrar"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head + row.group(0))
        self.assertNotIn("| Corta por bancos (R-35) | §2: motor vectorial", self.text)
        self.assertIn("Desde la spec 018", head)


@docs.requires_docs
class PitStateDocTest(unittest.TestCase):
    """Las trampas, el índice de specs, el roadmap, el README y el CHANGELOG dicen el estado de la 018."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.traps = one_line(docs.read(TRAPS_RELPATH))
        cls.index = docs.read(docs.SPECS_INDEX_RELPATH)
        cls.roadmap = docs.read(docs.ROADMAP_RELPATH)
        cls.readme = one_line(docs.read(README_RELPATH))
        cls.changelog = one_line(CHANGELOG_PATH.read_bytes().decode("utf-8"))

    def test_the_traps_of_the_plan_are_in_the_traps_document(self) -> None:
        """Plan 018 §10 y §2.1 (T-1 a T-3; T37): ``docs/trampas.md`` tiene las tres trampas nuevas, con su síntoma, su remedio y su fuente."""
        for trap in TRAPS:
            with self.subTest(trap=trap):
                self.assertIn(trap.lower(), self.traps.lower())
        for fact in ("gis.offset", "inglete", "720", "11.520", "los dos lados", "recinto de la polilínea más externa"):
            with self.subTest(fact=fact):
                self.assertIn(fact, self.traps)

    def test_the_index_says_the_018_state(self) -> None:
        """Definición de hecho §3.7 (T37): la fila 018 del índice dice que está **cerrada** (25/11/2026, por Samuel; spec 0.14), en `main`, con la T01 a la T37 hechas, su guía y lo abierto al cierre (T42)."""
        row = one_line(next(line for line in self.index.splitlines() if line.startswith("| 018 |")))
        for fact in ("de la T01 a la T37", "`docs/usuario/corta-por-bancos.md`", "**Cerrada** (25/11/2026, por Samuel: «Sí»; spec 0.14)", "`verificacion.md` §7",
                     "no concluyente", "-69,6 %", "CE-018-13", "DIFF-018k", "DIFF-001a"):
            with self.subTest(fact=fact):
                self.assertIn(fact, row)
        self.assertNotIn("sin cerrar", row.split("; antes: ")[0])

    def test_the_roadmap_says_r35_is_closed(self) -> None:
        """Plan 018 §5.6 (T37 y T42): R-35 pasa de «pendiente» a la spec 018 **hecha y cerrada** el 25/11/2026 (con R-36 y R-40 como dependencias y lo abierto de
        `verificacion.md` §7), con su registro del 24/11/2026 y el del cierre."""
        row = next(line for line in self.roadmap.splitlines() if line.startswith("| R-35 |"))
        self.assertNotIn("| pendiente |", row)
        for fact in ("018-des-corta-por-bancos", "R-36", "R-40", "**hecha**", "**cerrada** por Samuel el 25/11/2026 (spec 0.14)", "`verificacion.md` §7", "no concluyente",
                     "CE-018-13"):
            with self.subTest(fact=fact):
                self.assertIn(fact, row)
        self.assertNotIn("sin cerrar", row)
        self.assertTrue(any(line.startswith("| 2026-11-24 | R-35:") for line in self.roadmap.splitlines()))
        close = [line for line in self.roadmap.splitlines() if line.startswith("| 2026-11-25 | R-35:")]
        self.assertEqual(len(close), 1)
        for fact in ("Samuel cierra la spec 018", "spec 0.14", "no concluyente", "-69,6 %", "CE-018-13", "DIFF-018k", "la spec 019"):
            with self.subTest(close=fact):
                self.assertIn(fact, close[0])

    def test_the_readme_and_the_changelog_have_the_guide_and_the_entry(self) -> None:
        """Definición de hecho §3.7 (T37): el README de la carpeta enlaza la guía y la lista de guías la describe; el CHANGELOG del código tiene la entrada «Corta por bancos» en
        «Añadido», escrita para el ingeniero de minas: lo nuevo, las cifras HIPÓTESIS y lo que no hace todavía."""
        self.assertIn("(docs/usuario/corta-por-bancos.md)", self.readme)
        self.assertIn("(`corta-por-bancos.md`)", self.readme)
        entry = self.changelog[self.changelog.index("- **Corta por bancos**"):]
        entry = entry[:entry.index("- **Pistas y rampas**")]
        for fact in ("spec 018, R-35", "ascendente", "descendente", "roseta", "espiral", "zig-zag", "línea de cielo", "HIPÓTESIS", "Expandir banco…",
                     "cerrada por Samuel el 25/11/2026", "Abierto al cierre", "no concluyó", "-69,6 %", "no se vieron en pantalla", "no parte de la concha"):
            with self.subTest(fact=fact):
                self.assertIn(fact, entry)
        self.assertNotIn("sin cerrar", entry)
        self.assertIsNone(JARGON.search(entry), "el CHANGELOG se escribe para el ingeniero de minas, sin jerga de tareas")


if __name__ == "__main__":
    unittest.main()
