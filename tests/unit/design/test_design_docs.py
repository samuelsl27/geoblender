# SPDX-License-Identifier: GPL-3.0-or-later
"""Las envolventes y el escalonado frente a su documentación (spec 013, T37; hallazgo F-4 de la
verificación única; plan 013 §5.2.1, §5.2.2, §5.2.3 y §5.5; definición de hecho §3.7).

Como la cubicación (``tests/unit/reserves/test_res_docs.py``) y los límites
(``tests/unit/core/constraints/test_constraints_docs.py``), el código manda y la documentación lo
describe; estas pruebas avisan de que se separan:

- ``docs/arquitectura/datos/formato-proyecto.md``: §3.11 tiene una vez el SQL de
  ``des_bench_profile``, ``des_bmt_`` y ``des_rpt_``, igual que lo crea el código (salvo los
  comentarios, los espacios y las comillas); §4.2, las tres rejillas; §3.3, cada familia de
  parámetros;
- ``docs/arquitectura/modulos/des.md``: la API (§4.1, la 013, y §4.2, la 014: su T36) nombra cada
  módulo de ``design``, cada clase y función pública que define y nada que no exista; «Datos que
  posee» nombra sus datos, sus parámetros y sus cifras, también los de la 014; §1.2 no dice que el
  escalonado sea conservador sin decir frente a qué;
- la guía de uso ``docs/usuario/envolventes-y-escalonado.md``: **todo texto entre «» está en el
  catálogo** (los de ``core/i18n/messages.toml``, los de ``design.messages`` y los del catálogo de
  órdenes) **o es un ejemplo que la propia prueba lista**; las rutas de los datos, los parámetros y
  las órdenes son las del código; el cierre del proyecto a mitad de un cálculo y la marca de la
  búsqueda pendiente (y dónde sale: bajo el estado y junto a las cifras, T38) salen como los escribe
  el código; y dice lo que hace la regularización entre sectores cuando baja la envolvente (T35);
- el índice de specs, el roadmap, el ``CHANGELOG.md`` del código y la ficha de ``des`` dicen el estado
  de la 013 tras su verificación única (T34 a T38);
- los colores que dicen la guía, el ``CHANGELOG.md`` y la comprobación M2 de ``tasks.md`` son los que
  se ven: «ámbar» solo de lo que dibuja la vista 3D por sí misma; una etiqueta de Blender en alerta
  (las ventanas y la barra N) sale en rojo con un triángulo (T42; hallazgo del H3 (4)).
- la 016 (su T38): la ficha de ``des`` (§4.4: los siete módulos nuevos y lo que añade a los demás; «Datos que posee»: las
  ocho familias de datos, las cuatro de parámetros, las cifras y los cinco tipos de operación), ``formato-proyecto.md``
  (§3.3, §3.11 y §4.2), la guía ``docs/usuario/acopios-y-contrafuertes.md`` (todo texto entre «» sale del catálogo o es un
  ejemplo que la prueba lista; los umbrales, los datos y las cifras son los del código), el ADR-0031 (su fe de erratas),
  la barra superior, los paneles contextuales, el índice de specs, el roadmap y el ``CHANGELOG.md``.

Sin la carpeta de la documentación, se omiten (recurso ``docs``). Las pruebas del emparejado de las
citas (:class:`QuoteMatcherTest`) no la necesitan: comprueban que la regla no da falsos verdes.
"""

from __future__ import annotations

import inspect
import pkgutil
import re
import sqlite3
import unittest
from collections.abc import Iterable
from contextlib import closing

from tests.support import docs
from tests.support.bs_tables import backticked, section, tables
from tests.support.package import import_geoblender
from tests.support.repo import ROOT

design = import_geoblender("design")
dmessages = import_geoblender("design.messages")
dparams = import_geoblender("design.params")
dprofiles = import_geoblender("design.profiles")
dprov = import_geoblender("design.provenance")
dsectors = import_geoblender("design.sectors")
enlayer = import_geoblender("design.entity_layer")
dstore = import_geoblender("design.store")
dpreview = import_geoblender("design.preview")
provenance = import_geoblender("core.provenance")
gpkg_base = import_geoblender("core.gpkg.base")
i18n = import_geoblender("core.i18n")
catalog = import_geoblender("core.catalog")

GUIDE_RELPATH = "docs/usuario/envolventes-y-escalonado.md"
DES_RELPATH = "docs/arquitectura/modulos/des.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
SPECS_INDEX_RELPATH = docs.SPECS_INDEX_RELPATH
ROADMAP_RELPATH = docs.ROADMAP_RELPATH
CHANGELOG_PATH = ROOT / "CHANGELOG.md"

# El cierre del proyecto a mitad de un cálculo del diseño tiene su propio msgid; el de la cubicación
# (011) sigue como estaba y habla de cubicar.
CLOSED_MSGID = ("The project was closed while the design «{name}» was being computed: nothing "
                "has been left half-done")
CLOSED_ES = "Se cerró el proyecto mientras se calculaba «Hoyo»: no ha quedado nada a medias"
CUBICATION_MSGID = ("The project was closed while «{name}» was being computed: nothing has been "
                    "left half-done")
CUBICATION_ES = "Se cerró el proyecto mientras se cubicaba «Hoyo»: no ha quedado nada a medias"
MARK_ES = "Búsqueda de intocables pendiente en «Sector 2»."
# Hasta dónde llega la 013. Se escribe «de la T01 a la T40 y de la T42 a la T47» y no «T01 a T47»: la prueba de la 012
# (``test_indexes_reach_the_last_task``) exige que esa frase, que era la suya, ya no esté en el índice
# ni en el roadmap.
LAST_TASKS = "de la T01 a la T40 y de la T42 a la T47"

# Las órdenes de Diseño de la 013 que la guía nombra con el texto de su catálogo.
ORDERS = ("geoblender.des_edit_bench_profiles", "geoblender.des_edit_design_sectors",
          "geoblender.des_toggle_preview", "geoblender.des_compute_envelope",
          "geoblender.des_save_bench_profile", "geoblender.des_set_sector_slope",
          "geoblender.des_export_design_grid")

SQL_FENCE = re.compile(r"^```sql\n(.*?)^```", re.MULTILINE | re.DOTALL)
FENCE = re.compile(r"^```[^\n]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
COMMENT = re.compile(r"--[^\n]*")
CREATE = re.compile(r"^\s*CREATE\s+TABLE\s+\"?(des_\w+)\"?", re.IGNORECASE)

# De lo que la guía pone entre «», lo que no está en el catálogo. Cada uno es un ejemplo (un nombre,
# un código, una cifra) o un término de otra entrada; la prueba exige que siga estando en la guía y
# que no haya ninguno más: una frase de un mensaje que se cambia a mano deja de salir del catálogo y
# la prueba la nombra.
EXAMPLES = (
    # Nombres de objetos de un proyecto de ejemplo.
    "Hoyo", "Frente tendido", "PIZ_10_85_1",
    "Envolvente Hoyo · V01 [VIGENTE]",
    # Lo que la interfaz arma con partes del catálogo (el menú, lo que se asigna, lo que se siembra).
    "Diseño ▾", "Geoblender ▾ ▸ Diseño",
    "base REST_5_35_6, Frente tendido: …",
    "Semillas: celdas de «Topografía_2026» · zona de «Limite_legal»",
    # Términos que la guía explica y no son un texto de la interfaz.
    "No resuelto por la rejilla", "no resuelto por la rejilla",
    "NaN", "sin dato", "de diseño", "de cuadrícula",
    "límite legal ∪ lo que hay que sostener",
    # Lo que la guía dice que es de otra entrada (R-34).
    "ancla al fondo de cada muro", "solo donde corresponde",
)
# Valores de ejemplo que un mensaje lleva en un marcador y que la guía escribe (no entre «»).
EXAMPLE_VALUES = ("Sector 2", "superficie de partida", "la propiedad")
SHORT = 14  # los textos más cortos se comparan enteros: no «están» dentro de cualquier otro

# Los colores (T42; hallazgo del H3 (4)). El ámbar es de lo que la vista 3D dibuja por sí misma con
# ``gpu`` y ``blf`` (``bl.draw``: el borde de un sector con la búsqueda pendiente y las líneas de aviso
# del resumen de la vista previa) y del icono de [HIP]; una etiqueta de Blender en alerta (``alert``:
# las ventanas y la barra N) sale en rojo con un triángulo. Cada «ámbar» que quede en la guía y en la
# entrada de la 013 del ``CHANGELOG.md`` está aquí, y la prueba exige que siga estando.
AMBER_IN_THE_GUIDE = (
    "**en ámbar si su búsqueda está pendiente**",
    "Los avisos salen en ámbar en la vista y en rojo, con un triángulo, en la barra N.",
)
AMBER_IN_THE_CHANGELOG = ("(en ámbar si su búsqueda está pendiente)",)
TASKS_RELPATH = "specs/013-des-envolventes-y-escalonado/tasks.md"

# La guía de las entidades de diseño (spec 015, T34) y las órdenes de las entidades que nombra con el texto de
# su catálogo.
ENTITIES_GUIDE_RELPATH = "docs/usuario/entidades-de-diseno.md"
ENTITY_ORDERS = ("geoblender.des_create_platform", "geoblender.des_entity_dependents",
                 "geoblender.des_entity_insert", "geoblender.des_entity_bring",
                 "geoblender.des_entity_calculate", "geoblender.des_entity_discard",
                 "geoblender.des_entity_release_support", "geoblender.des_entity_preview",
                 "geoblender.des_export_design_grid")
# De lo que la guía de las entidades pone entre «», lo que no está en el catálogo: nombres de ejemplo, el nombre
# de una carpeta de comandos y términos que la guía explica. La prueba exige que siga en la guía y que no haya
# ninguno más.
ENTITY_EXAMPLES: tuple[str, ...] = (
    # Nombres de ejemplo de plataformas y de capas, y los mensajes que los llevan en un marcador.
    "P1", "P2", "Carga",
    "Origen: Plataforma P1 (PLT-001)", "Plataforma P1 (declarada)", "declarada por la plataforma P1",
    # Lo que arma la interfaz con partes del catálogo (el menú contextual) y un botón de la ventana de
    # restricciones de la 012.
    "Entidad ▾", "Completar…",
)

# Las secciones de la API de la ficha ``des.md``: lo de la 013, lo que añade la 014 (su T36), lo de la 015
# (su T34) y lo de la 016 (su T38). Un módulo puede tener fila en varias (lo de la 014 en un módulo de la 013, como
# ``design.store``): la prueba junta sus celdas.
API_SECTIONS = ("### 4.1 Lo que entrega la spec 013 (R-33)",
                "### 4.2 Lo que entrega la spec 014 (R-34)",
                "### 4.3 Lo que entrega la spec 015 (R-36)",
                "### 4.4 Lo que entrega la spec 016 (R-36)")

# El mecanismo de la 014, la 015 y la 016 para una spec que añade API pública mientras se construye: cada tarea
# añade aquí sus nombres (y los módulos nuevos, que aún no tienen fila en la ficha) y la tarea de documentación los
# lleva a la ficha y vacía estos dos conjuntos. Vacíos desde la T34 de la 015 (la ficha, ``des.md`` §4.3, nombra todo lo
# público de ``design``), otra vez desde su T47 y **desde la T38 de la 016** (``des.md`` §4.4 nombra los siete módulos
# nuevos y lo que la 016 añade a los demás); una spec posterior los usará con los suyos. El nombre ``PENDING_015_*`` se
# conserva porque otras pruebas lo importan.
PENDING_015_API: frozenset[str] = frozenset({
    # La 017, T02 y T03 (la tarea de documentación, T35, los lleva a la ficha, ``des.md`` §4.5, y vacía este conjunto):
    "AccessParam", "RoadParam", "RoadProfileParam", "check_road_profile", "check_road_profile_radii",
    "check_road_profile_value", "road_half_width_m", "road_profile_key",
    "access_figures", "access_inputs", "access_params", "propose_figures", "road_figures", "road_inputs",
    "road_operation_defs", "road_params", "reproduce_road", "reproduce_road_access", "reproduce_road_propose",
})
PENDING_015_MODULES: frozenset[str] = frozenset({
    # La 017, T04 (la tarea de documentación, T35, los lleva a la ficha, ``des.md`` §4.5, y vacía este conjunto):
    "design.road_profiles",
})


def one_line(text: str) -> str:
    """``text`` con cada salto de línea y sangría reducidos a un espacio, para buscar una frase
    que el documento parte en dos renglones."""
    return re.sub(r"\s+", " ", text)


def inline_tokens(text: str) -> set[str]:
    """Los textos entre comillas invertidas de ``text`` sin sus bloques de código."""
    return set(backticked(FENCE.sub(" ", text)))


def normalized(sql: str) -> str:
    """El SQL de una sentencia sin comentarios, sin comillas dobles y con los espacios reducidos
    (ninguno junto a paréntesis y comas)."""
    text = COMMENT.sub(" ", sql).replace('"', "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([(),])\s*", r"\1", text)
    return text.strip().rstrip(";").strip()


def documented_tables(document: str) -> dict[str, list[str]]:
    """Las sentencias ``CREATE TABLE des_…`` de los bloques ``sql`` del documento, normalizadas,
    por nombre."""
    found: dict[str, list[str]] = {}
    for block in SQL_FENCE.findall(document):
        for statement in COMMENT.sub(" ", block).split(";"):
            match = CREATE.match(statement)
            if match is not None:
                found.setdefault(match.group(1), []).append(normalized(statement))
    return found


def code_tables() -> dict[str, str]:
    """El SQL con que el código crea cada tabla de la 013, la 015 y la 016 (normalizado), con el nombre de
    ejemplo ``Hoyo`` (la 015, ``Carga``; la 016, ``Acopios`` y ``Refuerzo``, el de un contrafuerte) y la versión
    ``V01`` para las de una versión."""
    berms = dprov.dataset_locator(dprov.BERM_TABLE, "Hoyo", "V01")
    report = dprov.dataset_locator(dprov.REPORT_TABLE, "Hoyo", "V01")
    entity = dprov.dataset_locator(dprov.ENTITY_TABLE, "Carga", "V01")
    entity_report = dprov.dataset_locator(dprov.ENTITY_REPORT_TABLE, "Carga", "V01")
    entity_map = enlayer.entity_layer_table("V01")
    stockpiles = dprov.dataset_locator(dprov.STOCKPILES_TABLE, "Acopios", "V01")
    candidates = dprov.dataset_locator(dprov.STOCKPILE_CANDIDATES_TABLE, "Acopios", "V01")
    buttress = dprov.dataset_locator(dprov.ENTITY_TABLE, "Refuerzo", "V01")
    with closing(sqlite3.connect(":memory:")) as conn:
        gpkg_base.create_structure(conn)
        conn.execute("INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
                     "organization_coordsys_id, definition) VALUES ('t', 25830, 'EPSG', 25830, 'x')")
        dprofiles.create_table(conn)
        gpkg_base.create_attribute_table(conn, berms, dstore.BERM_COLUMNS, "bermas")
        gpkg_base.create_attribute_table(conn, report, dstore.REPORT_COLUMNS, "informe")
        gpkg_base.create_attribute_table(conn, entity, dstore.ENTITY_COLUMNS, "entidad")
        gpkg_base.create_attribute_table(conn, entity_report, dstore.REPORT_COLUMNS,
                                         "informe de la entidad")
        enlayer.create_entity_layer_table(conn, entity_map, 25830)
        gpkg_base.create_attribute_table(conn, stockpiles, dstore.STOCKPILE_COLUMNS, "acopios")
        gpkg_base.create_attribute_table(conn, candidates, dstore.CANDIDATE_COLUMNS, "candidatos")
        gpkg_base.create_attribute_table(conn, buttress, dstore.columns_of(dprov.BUTTRESS, dprov.ENTITY_TABLE),
                                         "entidad de un contrafuerte")
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    wanted = (dprofiles.TABLE, berms, report, entity, entity_report, entity_map, stockpiles, candidates, buttress)
    return {str(name): normalized(str(sql)) for name, sql in rows if name in wanted}


def raster_pattern(code: str, *, folder: bool) -> str:
    """El nombre de la rejilla de la familia ``code`` con ``<nombre>`` y ``<vNN>``, como lo
    escribe la documentación (con ``rasters/`` o sin ella)."""
    locator = dprov.dataset_locator(code, "Mi nombre", "V01")
    assert locator.endswith("mi_nombre_v01.tif"), locator
    shown = locator.replace("mi_nombre", "<nombre>").replace("v01", "<vNN>")
    return shown if folder else shown.removeprefix("rasters/")


def table_pattern(code: str) -> str:
    """El nombre de la tabla de la familia ``code`` con ``<nombre>`` y ``<vNN>``."""
    locator = dprov.dataset_locator(code, "Mi nombre", "V01")
    assert locator.endswith("mi_nombre_v01"), locator
    return locator.replace("mi_nombre", "<nombre>").replace("v01", "<vNN>")


# --- Las citas entre «» -----------------------------------------------------------------------


def quotes(text: str) -> list[str]:
    """Las citas de nivel 1 de ``text``: lo que hay entre un «, y su » de cierre, con las que lleva
    dentro (``«Se cerró «Hoyo»»`` es una). Un cierre sin apertura o una apertura sin cierre es un
    error del documento: :class:`ValueError`."""
    found: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "«":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == "»":
            depth -= 1
            if depth < 0:
                raise ValueError(f"un » sin su «: …{text[max(0, index - 50):index + 1]}")
            if depth == 0:
                found.append(re.sub(r"\s+", " ", text[start:index]))
    if depth != 0:
        raise ValueError(f"un « sin su »: …{text[start:start + 60]}")
    return found


def pattern(text: str) -> str:
    """``text`` con lo que cambia de un uso a otro reducido a ``§``: los marcadores ``{x}``, lo que
    va entre «» (un nombre de un proyecto), las versiones y sus revisiones, los estados en
    mayúsculas, los números y la «N» de «N celdas». Así «Envolvente «Hoyo»: 38.412 celdas» y
    «Envolvente «{name}»: {cells} celdas» son el mismo texto."""
    text = text.replace("\xa0", " ").replace(" ", " ").replace("\\n", " ")
    text = re.sub(r"\{[^}]*\}", "§", text)
    text = re.sub(r"\s+", " ", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"«[^«»]*»", "§", text)
    for value in EXAMPLE_VALUES:
        text = text.replace(value, "§")
    text = re.sub(r"\[[A-Z]+\]", "§", text)  # la insignia del tipo de un valor: [ADO]
    text = re.sub(r"\bV\d+(?:\.r\d+)?", "§", text)
    text = re.sub(r"\b[A-ZÁÉÍÓÚ]{4,}\b", "§", text)
    text = re.sub(r"\d[\d.,]*", "§", text)
    text = re.sub(r"\bN\b", "§", text)
    text = re.sub(r"§ ?(?:m²|m³|ha|m|°|%)(?!\w)", "§", text)  # la unidad va con el valor
    return re.sub(r"(§ ?)+", "§ ", text).strip()


def fragments(quote: str) -> list[str]:
    """Las partes de una cita separadas por lo que la guía omite (``…``) o por «/» (dos textos
    posibles), ya en forma de :func:`pattern` y sin signos en los extremos; sin las que no dicen
    nada (solo un marcador)."""
    out = []
    squeezed = re.sub(r"«[^«»]*»", "«§»", quote)
    previous = None
    while previous != squeezed:
        previous = squeezed
        squeezed = re.sub(r"«[^«»]*»", "§", squeezed).replace("«§»", "§")
    for piece in re.split(r"…|\s/\s", squeezed):
        shown = pattern(piece).strip(" ,.;:·")
        if shown and shown != "§":
            out.append(shown)
    return out


def catalog_texts() -> list[str]:
    """Todo texto en español que el código puede mostrar: el catálogo de la interfaz, el de
    ``design``, el de las órdenes y las familias de datos del diseño."""
    texts = list(i18n.load_messages().values())
    texts += [message.es for message in dmessages.CATALOG]
    texts += list(catalog.load().translations().values())
    texts += [family.label for family in dprov.FAMILIES]
    return texts


class QuoteIndex:
    """Los textos del catálogo en forma de :func:`pattern`, para decir si una cita sale de ellos."""

    def __init__(self, texts: Iterable[str]) -> None:
        self.texts = sorted({pattern(text) for text in texts})
        self.whole = {text.strip(" .") for text in self.texts}

    def has(self, quote: str) -> bool:
        """``quote`` sale del catálogo: sus partes, en orden, dentro de un mismo texto; o, si es
        corta (menos de :data:`SHORT` caracteres), un texto entero."""
        parts = fragments(quote)
        if not parts:
            return True  # solo marcadores: nada que comparar
        if sum(len(part) for part in parts) < SHORT:
            return len(parts) == 1 and parts[0] in self.whole
        for text in self.texts:
            at = 0
            for part in parts:
                found = text.find(part, at)
                if found < 0:
                    break
                at = found + len(part)
            else:
                return True
        return False


# --- Pruebas sin la documentación --------------------------------------------------------------


class QuoteMatcherTest(unittest.TestCase):
    """La regla que empareja las citas de la guía con el catálogo no da falsos verdes: lo que sale
    del catálogo pasa, con cifras y nombres de otro proyecto y con lo omitido, y lo que se cambia a
    mano, una palabra, una comilla o una frase entera, no."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = QuoteIndex(catalog_texts())

    def test_a_rendered_message_passes_with_other_names_and_numbers(self) -> None:
        """Principio 10 (T37): un mensaje del catálogo escrito con un nombre, unas cifras y una
        versión de ejemplo pasa, entero y por partes."""
        shown = dmessages.render("des.regularization_lowered", cells=12, drop=3.5, slope=12.0,
                                 sectors="Sector 2")
        self.assertTrue(self.index.has(shown))
        self.assertTrue(self.index.has(
            "La regularización entre sectores con taludes generales distintos bajó la envolvente "
            "más que la tolerancia en 4.210 celdas (hasta 7 m; sectores: Sector 2)… suba el talud "
            "general máximo impuesto del sector"))
        self.assertTrue(self.index.has("V02 está en estado SUPERADO: cree una versión nueva a "
                                       "partir de ella"))
        self.assertTrue(self.index.has("Se cerró el proyecto mientras se calculaba «Otro»: no ha "
                                       "quedado nada a medias"))

    def test_a_changed_word_or_a_whole_new_sentence_fails(self) -> None:
        """Principio 10 (T37): una palabra cambiada, otra frase o la frase de otro mensaje no
        pasan; tampoco lo que dice la guía de una versión anterior."""
        for quote in (
                "Se cerró el proyecto mientras se calculaban «Hoyo»: no ha quedado nada a medias",
                "El proyecto se cerró mientras se calculaba «Hoyo»: no queda nada a medias",
                "La regularización entre sectores con taludes generales distintos subió la "
                "envolvente más que la tolerancia en 12 celdas",
                "Las semillas de tipo «cota fija» necesitan «zona» y también una cota o dos",
                "Una frase que ningún mensaje de Geoblender dice"):
            with self.subTest(quote=quote):
                self.assertFalse(self.index.has(quote))

    def test_a_short_text_must_be_a_whole_text(self) -> None:
        """Principio 10 (T37): «Crear» es un texto del catálogo; «Crearr», «Calculando» o «cancel»
        no lo son, aunque estén dentro de otros más largos."""
        self.assertTrue(self.index.has("Crear"))
        self.assertTrue(self.index.has("Al día"))
        for quote in ("Crearr", "Calculando", "Esc", "Al dia"):
            with self.subTest(quote=quote):
                self.assertFalse(self.index.has(quote))

    def test_quotes_and_unbalanced_guillemets(self) -> None:
        """Las citas de nivel 1 llevan dentro las anidadas; un » sin « o un « sin » es un error
        del documento."""
        self.assertEqual(quotes("a «Se cerró «Hoyo»: nada» y «Crear» b"),
                         ["Se cerró «Hoyo»: nada", "Crear"])
        self.assertEqual(quotes("«Un texto\n   en dos renglones»"), ["Un texto en dos renglones"])
        for broken in ("«Hoyo", "Hoyo»", "«a» «b"):
            with self.subTest(text=broken), self.assertRaises(ValueError):
                quotes(broken)

    def test_every_listed_example_is_not_in_the_catalog(self) -> None:
        """Un ejemplo de :data:`EXAMPLES` que sí está en el catálogo sobra: la lista solo tiene lo
        que no sale de él (si no, un cambio de un mensaje no se vería)."""
        for example in EXAMPLES:
            with self.subTest(example=example):
                self.assertFalse(self.index.has(example))


# --- Pruebas con la documentación ---------------------------------------------------------------


@docs.requires_docs
class ProjectFormatDocTest(unittest.TestCase):
    """``formato-proyecto.md`` describe las tablas, las rejillas y los parámetros de la 013."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(FORMAT_RELPATH)

    def test_tables_as_in_the_code(self) -> None:
        """RF-013-18, RF-013-28, RF-013-30 (plan 013 §5.2.1 y §5.2.3, D-17, D-24, D-26), RF-015-02 y
        RF-015-27 (plan 015 §5.2.3; T34) y RF-016-02, RF-016-08, RF-016-17 (plan 016 §5.2.3; T38): §3.11 tiene una vez el SQL de ``des_bench_profile``, de
        ``des_bmt_`` (las cotas reales de las bermas) y de ``des_rpt_`` (el informe) y, de la 015, de
        ``des_epr_`` (la entidad), ``des_prp_`` (su informe) y ``des_enl_`` (la capa de entidades), el
        que escribe el código y, de la 016, el de ``des_stk_`` (los acopios), ``des_stc_`` (sus candidatos) y la
        ``des_epr_`` de un contrafuerte (con su zona de coronación); ``des_decl_`` (las restricciones declaradas) está
        en §3.9 (``test_constraints_docs``)."""
        documented = documented_tables(section(self.text, "### 3.11 Tablas de los módulos"))
        in_code = code_tables()
        self.assertEqual(len(in_code), 9)
        for name in (dprofiles.TABLE, *(
                dprov.dataset_locator(code, "Hoyo", "V01")
                for code in (dprov.BERM_TABLE, dprov.REPORT_TABLE)),
                *(dprov.dataset_locator(code, "Carga", "V01")
                  for code in (dprov.ENTITY_TABLE, dprov.ENTITY_REPORT_TABLE)),
                enlayer.entity_layer_table("V01"),
                dprov.dataset_locator(dprov.STOCKPILES_TABLE, "Acopios", "V01"),
                dprov.dataset_locator(dprov.STOCKPILE_CANDIDATES_TABLE, "Acopios", "V01"),
                dprov.dataset_locator(dprov.ENTITY_TABLE, "Refuerzo", "V01")):
            with self.subTest(table=name):
                self.assertEqual(documented.get(name, []), [in_code[name]])
        self.assertEqual(sorted(documented), sorted(in_code), "una tabla des_ que el código no crea")

    def test_grids_and_parameter_families(self) -> None:
        """RF-013-17, RF-013-18, RF-013-30 (plan 013 §5.2.2 y §5.2.3, D-26; ADR-0027, ADR-0029): §4.2
        nombra las tres rejillas de una operación, §3.11, las dos tablas y la de los perfiles, y
        §3.3, cada familia de parámetros y los dos del proyecto."""
        rasters = inline_tokens(section(self.text, "### 4.2 `rasters/` — GeoTIFF"))
        for family in dprov.FAMILIES:
            if family.extension:
                with self.subTest(grid=family.code):
                    self.assertIn(raster_pattern(family.code, folder=False), rasters)
        tables_text = section(self.text, "### 3.11 Tablas de los módulos")
        named = inline_tokens(tables_text)
        self.assertIn(dprofiles.TABLE, named)
        for code in (dprov.BERM_TABLE, dprov.REPORT_TABLE):
            with self.subTest(table=code):
                self.assertIn(table_pattern(code), named)
        for op in (dprofiles.EDIT_BENCH_PROFILES,):
            self.assertIn(op, named)
        parameters = inline_tokens(section(
            self.text, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados"))
        for family in dparams.FAMILIES:
            with self.subTest(family=family.pattern):
                self.assertIn(family.pattern, parameters)
        for definition in dparams.DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, parameters)


@docs.requires_docs
class ModuleCardDocTest(unittest.TestCase):
    """``modulos/des.md`` nombra la API y los datos de ``design`` y no promete lo que el código no
    hace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(DES_RELPATH)
        cls.rows: dict[str, str] = {}
        for heading in API_SECTIONS:
            for table in tables(section(cls.text, heading)):
                for cells in table:
                    names = backticked(cells[0])
                    if names and names[0].startswith("design."):
                        cls.rows[names[0]] = f"{cls.rows.get(names[0], '')} {cells[1]}".strip()

    @staticmethod
    def named(cell: str) -> tuple[set[str], list[str]]:
        """Los símbolos que nombra la celda de una fila (la firma y los ``(_steps)`` aparte) y los
        sufijos de los que escribe como ``*_settings``."""
        found: set[str] = set()
        suffixes: list[str] = []
        for token in backticked(cell):
            if token.startswith("*"):
                suffixes.append(token[1:])
                continue
            match = re.match(r"[A-Za-z_]\w*", token)
            if match is not None:
                found.add(match.group())
                if token.startswith(f"{match.group()}(_steps)"):
                    found.add(f"{match.group()}_steps")
        return found, suffixes

    def test_api_names_every_module_class_and_function_and_nothing_else(self) -> None:
        """RF-013-01 a RF-013-34, RF-014-01 a RF-014-32 (plan 013 §5.1 y §5.3.1; plan 014 §5.1 y
        §5.3.1; T36 de la 014): la API (§4.1 y §4.2) tiene una fila por cada módulo de ``design``,
        también los de la 014, nombra cada clase y función pública que define (con ``__all__``) y
        todo lo que nombra existe en su módulo."""
        modules = [f"design.{info.name}" for info in pkgutil.iter_modules(design.__path__)]
        self.assertGreaterEqual(len(modules), 26)
        self.assertEqual(sorted(set(self.rows) - set(modules)), [], "una fila sin módulo")
        for dotted in modules:
            with self.subTest(module=dotted):
                if dotted in PENDING_015_MODULES and dotted not in self.rows:
                    continue
                self.assertIn(dotted, self.rows)
                module = import_geoblender(dotted)
                found, suffixes = self.named(self.rows[dotted])
                public = [name for name in getattr(module, "__all__", ())
                          if (inspect.isclass(getattr(module, name))
                              or inspect.isfunction(getattr(module, name)))
                          and getattr(module, name).__module__ == module.__name__]
                missing = [name for name in public if name not in found
                           and name not in PENDING_015_API
                           and not any(name.endswith(suffix) for suffix in suffixes)]
                self.assertEqual(missing, [])
                self.assertEqual(sorted(name for name in found if not hasattr(module, name)), [])

    def test_owned_data_parameters_figures_and_operations(self) -> None:
        """RF-013-17, RF-013-18, RF-013-30, RF-013-31 (plan 013 §5.2; ADR-0027, ADR-0029): «Datos
        que posee» nombra cada familia de datos del diseño, cada familia de parámetros y los dos del
        proyecto, cada cifra, y la ficha, los dos tipos de operación y la de los perfiles."""
        owned = inline_tokens(section(self.text, "## Datos que posee"))
        for family in dprov.FAMILIES:
            shown = (raster_pattern(family.code, folder=False).removesuffix(".tif")
                     if family.extension else table_pattern(family.code))
            with self.subTest(dataset=family.code):
                self.assertIn(shown, owned)
        self.assertIn(dprofiles.TABLE, owned)
        for family in dparams.FAMILIES:
            last = family.pattern.rsplit(".", 1)[1]
            with self.subTest(family=family.pattern):  # la ficha abrevia las de un perfil: «.face_deg»
                self.assertTrue(family.pattern in owned or f".{last}" in owned)
        for definition in dparams.DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, owned)
        for figure in dprov.FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, owned)
        named = inline_tokens(self.text) | set(re.findall(r"\bdes\.[a-z_]+\b", self.text))
        for op in (dprov.ENVELOPE, dprov.STEPPED, dprofiles.EDIT_BENCH_PROFILES):
            with self.subTest(operation=op):
                self.assertIn(op, named)

    def test_owned_data_parameters_figures_and_operations_of_the_014(self) -> None:
        """RF-014-16, RF-014-29, RF-014-32 (plan 014 §5.2.2 y §5.2.3; T36): «Datos que posee» nombra
        también cada familia de datos de la 014 (las rejillas y las dos tablas), sus siete
        parámetros y sus cifras, y la ficha, sus cinco tipos de operación."""
        owned = inline_tokens(section(self.text, "## Datos que posee"))
        for family in dprov.QUARRY_FAMILIES:
            shown = (raster_pattern(family.code, folder=False).removesuffix(".tif")
                     if family.extension else table_pattern(family.code))
            with self.subTest(dataset=family.code):
                self.assertIn(shown, owned)
        for definition in dparams.QUARRY_DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, owned)
        for figure in dprov.QUARRY_FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, owned)
        named = inline_tokens(self.text)
        for op in dprov.QUARRY_OPERATION_TYPES:
            with self.subTest(operation=op.op_type):
                self.assertIn(op.op_type, named)

    def test_a_stepped_design_is_conservative_against_the_regularized_envelope(self) -> None:
        """RF-013-22, RF-013-26, RF-013-30 (spec 0.4; F-4, punto 4): §1.2 no dice sin más que cada
        escalonado excava o rellena de menos: lo hace frente a la envolvente regularizada, y si la
        regularización baja la envolvente registrada lo dice el aviso ``des.regularization_lowered``
        (en corte puede quedar por debajo de la registrada; en relleno, rellena menos)."""
        text = one_line(section(self.text, "### 1.2 Escalonado anclado a cotas absolutas "
                                           "(DIS-02, DIS-03)"))
        self.assertNotIn("Cada escalonado es **conservador en su sentido** (excava o rellena de "
                         "menos).", text)
        for fact in ("conservador", "envolvente regularizada", "envolvente registrada",
                     dmessages.MESSAGES["des.regularization_lowered"].code,
                     "por debajo de la envolvente registrada", "rellena menos"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        shown = dmessages.MESSAGES["des.regularization_lowered"].es
        for fact in ("por debajo de la envolvente registrada", "rellena menos"):
            with self.subTest(message=fact):
                self.assertIn(fact, shown)

    def test_the_state_of_the_013(self) -> None:
        """Definición de hecho §3.7 (F-4, punto 1): la ficha dice que la 013 llega a la T38, con su
        verificación única, y no a la T32."""
        head = one_line(self.text[:self.text.index("## Responsabilidad")])
        row = re.search(r"^\| 013-des-envolventes-y-escalonado .*$", self.text, re.MULTILINE)
        self.assertIsNotNone(row)
        assert row is not None
        for name, text in (("cabecera", head), ("fila de la tabla", row.group(0))):
            with self.subTest(place=name):
                self.assertIn(LAST_TASKS, text)
                self.assertNotIn("T01 a T32", text)
                self.assertIn("verificación única", text)


@docs.requires_docs
class GuideDocTest(unittest.TestCase):
    """La guía de uso de las envolventes y el escalonado dice lo que el código hace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = docs.read(GUIDE_RELPATH)
        cls.index = QuoteIndex(catalog_texts())

    def guide_section(self, heading: str) -> str:
        return one_line(section(self.guide, heading))

    def test_every_quoted_text_is_in_the_catalog_or_is_a_listed_example(self) -> None:
        """Principio 10, RF-013-05, RF-013-16, RF-013-30 (T37; F-4, punto 5): todo texto de la guía
        entre «» sale del catálogo (``messages.toml``, ``design.messages``, las órdenes y las
        familias de datos del diseño: con otras cifras y otros nombres, y con lo que omite con «…»)
        o está en :data:`EXAMPLES`; y todo lo de :data:`EXAMPLES` sigue en la guía."""
        found = quotes(self.guide)
        self.assertGreater(len(found), 90)
        unknown = sorted({quote for quote in found
                          if quote not in EXAMPLES and not self.index.has(quote)})
        self.assertEqual(unknown, [], "textos de la guía que el catálogo no dice (cámbielos en la "
                                      "guía, o en el código si es él el que está mal)")
        self.assertEqual(sorted(set(EXAMPLES) - set(found)), [],
                         "ejemplos que la guía ya no cita: quítelos de EXAMPLES")

    def test_orders_are_named_with_their_catalog_text(self) -> None:
        """RF-013-33, RF-013-34 (plan 013 §5.3.3): la guía nombra cada orden de Diseño de la 013 con
        el texto de su catálogo y dónde está cada una."""
        cat = catalog.load()
        for key in ORDERS:
            with self.subTest(order=key):
                self.assertIn(cat.commands[key].label_es, self.guide)

    def test_data_paths_and_parameters_are_the_code_s(self) -> None:
        """RF-013-17, RF-013-18, RF-013-28, RF-013-30 (plan 013 §5.2): §14 da la ruta de cada rejilla,
        la tabla de cada familia y la de los perfiles como las nombra el código, y §13, cada familia
        de parámetros y los dos del proyecto."""
        where = inline_tokens(self.guide_section_text("## 14. Dónde queda cada cosa en el proyecto"))
        for family in dprov.FAMILIES:
            shown = (raster_pattern(family.code, folder=True) if family.extension
                     else table_pattern(family.code))
            with self.subTest(dataset=family.code):
                self.assertIn(shown, where)
        self.assertIn(dprofiles.TABLE, where)
        parameters = inline_tokens(self.guide_section_text("## 13. Los parámetros"))
        for family in dparams.FAMILIES:
            with self.subTest(family=family.pattern):
                self.assertIn(family.pattern, parameters)
        for definition in dparams.DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, parameters)
        self.assertIn(dparams.VERIFY_MIN_THICKNESS, parameters)

    def guide_section_text(self, heading: str) -> str:
        return section(self.guide, heading)

    def test_the_closed_project_message_is_its_own(self) -> None:
        """RF-013-33, D-14 (F-4, punto 2): cerrar el proyecto a mitad de un cálculo del diseño dice
        «Se cerró el proyecto mientras se calculaba «Hoyo»: no ha quedado nada a medias», con su
        propio *msgid*; el de la cubicación (011) sigue diciendo que se cubicaba. La guía (§12) lo
        cita como sale."""
        self.assertEqual(i18n.translate("es", CLOSED_MSGID, name="Hoyo"), CLOSED_ES)
        self.assertEqual(i18n.translate("es", CUBICATION_MSGID, name="Hoyo"), CUBICATION_ES)
        self.assertNotEqual(CLOSED_MSGID, CUBICATION_MSGID)
        text = self.guide_section("## 12. Mientras calcula, Esc y solo lectura")
        self.assertIn(f"«{CLOSED_ES}»", text)
        for stale in ("El proyecto se cerró mientras", "se cubicaba", "mientras se calculaba «Hoyo»: no "
                      "queda"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)

    def test_the_pending_search_mark_is_quoted_as_it_comes_out(self) -> None:
        """RF-013-06 (F-4, punto 3; T38, F-2): la marca de la búsqueda pendiente sale «Búsqueda de
        intocables pendiente en «Sector 2».» (el nombre entre «», y el punto final); la guía la cita
        así en §3.2 y en §9, y dice dónde sale: la barra N, bajo su estado y como las primeras filas
        del bloque «Cifras», en rojo con un triángulo y una por sector pendiente (es una etiqueta en
        alerta de la barra N, no un dibujo de la vista 3D); no se escribe en el proyecto, así
        que el informe y las cifras guardados no cambian ni la llevan (§3.2 y §10)."""
        mark = dsectors.PendingMark("sector_2", "Sector 2")
        self.assertEqual(mark.text("es"), MARK_ES)
        self.assertEqual(dmessages.render("des.sector_pending_mark", sector="Sector 2"),
                         "Búsqueda de intocables pendiente en Sector 2.")
        for heading in ("### 3.2 Los límites, las restricciones y los sectores al día",
                        "## 9. El resumen del escalonado, los avisos y el informe"):
            with self.subTest(section=heading):
                text = self.guide_section(heading)
                self.assertIn(f"«{MARK_ES}»", text)
                self.assertNotIn("pendiente en Sector 2", text)
        notes = self.guide_section("### 3.2 Los límites, las restricciones y los sectores al día")
        for fact in ("en la barra N", "debajo de su estado", "en rojo, con un triángulo, y una por cada sector pendiente",
                     "como las primeras filas del bloque «Cifras»", "justo encima de las cifras",
                     "es del estado de ahora, no del cálculo", "no se escribe en el proyecto",
                     "no cambian", "no la llevan"):
            with self.subTest(section="3.2", fact=fact):
                self.assertIn(fact, notes)
        shown = self.guide_section("## 10. Ver el resultado y exportarlo")
        for fact in ("la marca de la búsqueda pendiente, una por sector (§3.2)",
                     "las **cifras** de la operación, que empiezan por esa misma marca",
                     "las cifras guardadas no cambian"):
            with self.subTest(section="10", fact=fact):
                self.assertIn(fact, shown)
        self.assertNotIn("y la marca de la búsqueda pendiente;", shown)

    def test_the_regularization_that_lowers_the_envelope_is_told(self) -> None:
        """RF-013-22, RF-013-26, RF-013-30 (spec 0.4; T35; F-4, punto 4): la guía dice, en §8 y en el
        aviso de §9, lo que hace la regularización entre sectores cuando la envolvente es más
        empinada que el talud de los sectores: la baja, el escalonado en corte puede quedar por
        debajo de la registrada y en relleno rellena menos, y qué hacer (la pendiente «Talud de cada
        sector», que el diálogo llama «Por sectores», o subir el talud impuesto)."""
        shown = dmessages.MESSAGES["des.regularization_lowered"].es
        self.assertEqual(dmessages.MESSAGES["des.regularization_lowered"].severity, "warning")
        between = self.guide_section("## 8. Escalonar: bancos, bermas y la superficie de diseño")
        for fact in ("**Entre sectores.**", "más empinada que", "puede bajar la envolvente",
                     "por debajo de la envolvente registrada", "rellena menos", "aviso",
                     "Por sectores", "talud general máximo"):
            with self.subTest(section="8", fact=fact):
                self.assertIn(fact, between)
        warnings = self.guide_section("## 9. El resumen del escalonado, los avisos y el informe")
        for fact in ("La regularización entre sectores con taludes generales distintos bajó la "
                     "envolvente más que la tolerancia", "Talud de cada sector",
                     "por debajo de la envolvente registrada", "rellena menos"):
            with self.subTest(section="9", fact=fact):
                self.assertIn(fact, warnings)
        for fact in ("Talud de cada sector", "talud general máximo impuesto"):
            with self.subTest(message=fact):
                self.assertIn(fact, shown)
        self.assertEqual(i18n.translate("es", "Slope of each sector"), "Talud de cada sector")
        self.assertEqual(i18n.translate("es", "By sectors"), "Por sectores")
        self.assertNotIn("la envolvente (ya regularizada si hay sectores)", between)

    def test_the_guide_says_it_passed_the_single_verification(self) -> None:
        """Definición de hecho §3.7 (F-4): el recuadro del principio de la guía dice que la 013 pasó
        su verificación única (04/11/2026)."""
        head = one_line(self.guide[:self.guide.index("Antes de excavar un hueco")])
        self.assertIn("verificación única", head)
        self.assertIn("04/11/2026", head)


@docs.requires_docs
class StateDocTest(unittest.TestCase):
    """El índice de specs, el roadmap y el ``CHANGELOG.md`` dicen el estado de la 013 tras su
    verificación única (definición de hecho §3.7; F-4, punto 1)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.specs = docs.read(SPECS_INDEX_RELPATH)
        cls.roadmap = docs.read(ROADMAP_RELPATH)
        start = cls.specs.index("**La 013**")
        cls.paragraph = one_line(cls.specs[start:cls.specs.index("- **Lo que queda en la 013:**")])
        left = cls.specs.index("- **Lo que queda en la 013:**")
        cls.left = one_line(cls.specs[left:cls.specs.index("- **Lo que queda de personas en la 009:**")])
        cls.index_row = re.search(r"^\| 013 \|.*$", cls.specs, re.MULTILINE)
        cls.roadmap_row = re.search(r"^\| R-33 \|.*$", cls.roadmap, re.MULTILINE)
        cls.ledger = re.findall(r"^\| 2026-11-04 \| R-33.*$", cls.roadmap, re.MULTILINE)

    def test_the_index_says_where_the_013_is(self) -> None:
        """Definición de hecho §3.7 (F-4, punto 1): el párrafo de la 013, su fila de la tabla y lo
        que queda dicen que está en la 0.5, que llega a la T40 y de la T42 a la T47 con su verificación única (T34) y
        sus tareas de convergencia (T35 a T40 y T42 a T47), que el límite de ``check.py`` ya es de 48 s y lo
        que queda (el H3, CE-013-10, CE-013-11 y ``Z:``), y no hablan de la T32 ni de la 0.3
        como lo último ni de lo ya decidido como pendiente."""
        self.assertIsNotNone(self.index_row)
        assert self.index_row is not None
        for name, text in (("párrafo", self.paragraph), ("fila", self.index_row.group(0))):
            with self.subTest(place=name):
                self.assertIn("0.5", text)
                self.assertIn(LAST_TASKS, text)
                self.assertIn("verificación única", text)
                self.assertNotIn("T01 a T32", text)
                self.assertNotIn("T01 a la T32", text)
                self.assertNotIn("faltan la T33", text)
                self.assertNotIn("spec 0.3", text)
        self.assertIn("48 s", self.paragraph)
        self.assertIn("T35 a T40 y T42 a T47", self.paragraph)
        for fact in ("H3", "CE-013-10", "CE-013-11", "`Z:`", "diff de la T32"):
            with self.subTest(left=fact):
                self.assertIn(fact, self.left)
        for stale in ("T33 (el arnés", "decidir el límite", "T34 (la verificación única"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.left)

    def test_the_roadmap_says_where_the_013_is(self) -> None:
        """Definición de hecho §3.7 (F-4, punto 1): la fila de R-33, su *Spec* y el registro del
        04/11/2026 dicen la 0.5, que llega a la T38 con su verificación única y lo que queda."""
        self.assertIsNotNone(self.roadmap_row)
        assert self.roadmap_row is not None
        row = self.roadmap_row.group(0)
        for fact in (LAST_TASKS, "verificación única", "T38", "CE-013-10", "CE-013-11"):
            with self.subTest(row=fact):
                self.assertIn(fact, row)
        for stale in ("T01 a T32", "faltan la T33", "la T34 (verificación única)"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, row)
        bullet = one_line(self.roadmap[self.roadmap.index("**R-33 · Envolventes y escalonado.**"):
                                       self.roadmap.index("**R-34 · Cantera con dos superficies.**")])
        self.assertIn("versión 0.5", bullet)
        self.assertNotIn("versión 0.3", bullet)
        self.assertTrue(any("T37" in entry and "verificación única" in entry
                            for entry in self.ledger), self.ledger)
        self.assertTrue(any("T38" in entry and "RF-013-06" in entry for entry in self.ledger),
                        self.ledger)

    def test_the_changelog_says_the_013_passed_its_single_verification(self) -> None:
        """Definición de hecho §3.7 (F-4, punto 1): el ``CHANGELOG.md`` del código dice que la 013
        pasó su verificación única (04/11/2026) y ya no la lista entre lo que falta, y que cerrar
        el proyecto a mitad de un cálculo del diseño no habla de cubicar."""
        text = one_line(CHANGELOG_PATH.read_text(encoding="utf-8"))
        start = text.index("Lo de la spec 013 está comprobado")
        entry = text[start:text.index("### Añadido")]
        self.assertIn("pasó su verificación única (04/11/2026)", entry)
        self.assertNotIn("las medidas en `Z:`, su verificación única", entry)
        bullet = text[text.index("- **Envolventes y escalonado** (spec 013)"):
                      text.index("- **Límites legales y restricciones** (spec 012)")]
        self.assertIn(f"«{CLOSED_ES}»", bullet)


@docs.requires_docs
class ColourDocTest(unittest.TestCase):
    """Los colores que dicen la guía, el ``CHANGELOG.md`` y la comprobación M2 son los que se ven
    (T42; hallazgo del H3 (4)): lo que sale en una etiqueta en alerta de una ventana o de la barra N es
    rojo con un triángulo, y solo lo que la vista 3D dibuja por sí misma es ámbar."""

    def only_the_drawn_amber(self, text: str, allowed: tuple[str, ...], where: str) -> None:
        """Que cada frase de ``allowed`` siga en ``text`` y que no quede otro «ámbar»."""
        for phrase in allowed:
            with self.subTest(where=where, phrase=phrase):
                self.assertIn(phrase, text)
        rest = text
        for phrase in allowed:
            rest = rest.replace(phrase, " ")
        left = [found.group(0) for found in re.finditer(r".{0,70}ámbar.{0,40}", rest)]
        self.assertEqual(left, [], f"«ámbar» de {where} que no es de lo que dibuja la vista 3D: una "
                                   "etiqueta de Blender en alerta sale en rojo, con un triángulo")

    def test_the_guide_says_amber_only_for_what_the_3d_view_draws(self) -> None:
        """RF-013-03, RF-013-06, RF-013-20, RF-013-31 (T42; H3 (4)): en la guía solo es ámbar el borde
        de los sectores pendientes de la vista previa y sus avisos en la vista 3D; el perfil «no
        resuelto por la rejilla», el estado «Búsqueda pendiente» de los sectores, la lista de lo que
        cuelga de un sector que ya no existe, los avisos del resumen del cálculo, el sector pendiente
        del diálogo y la marca de la búsqueda pendiente de la barra N salen en rojo con su
        triángulo."""
        text = one_line(docs.read(GUIDE_RELPATH))
        self.only_the_drawn_amber(text, AMBER_IN_THE_GUIDE, "la guía")
        for fact in ("el perfil sale en rojo, con un triángulo:",
                     "o, en rojo, con un triángulo, «Búsqueda pendiente»",
                     "sale en una lista aparte, en rojo («Parámetros sin sector»",
                     "más los avisos, en rojo, con un triángulo (",
                     "lleva, en rojo, «Búsqueda pendiente»",
                     "en rojo y con un triángulo, la marca de la búsqueda pendiente, una por sector"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_changelog_says_amber_only_for_what_the_3d_view_draws(self) -> None:
        """RF-013-03, RF-013-06, RF-013-20 (T42; H3 (4)): en la entrada de la 013 del ``CHANGELOG.md``
        solo es ámbar el borde de los sectores pendientes de la vista previa; el perfil «no resuelto
        por la rejilla» y la marca de la barra N salen en rojo, con un triángulo."""
        text = one_line(CHANGELOG_PATH.read_text(encoding="utf-8"))
        bullet = text[text.index("- **Envolventes y escalonado** (spec 013)"):
                      text.index("- **Límites legales y restricciones** (spec 012)")]
        self.only_the_drawn_amber(bullet, AMBER_IN_THE_CHANGELOG, "el CHANGELOG")
        for fact in ("lo marca «no resuelto por la rejilla» en rojo, con un triángulo, si su cara",
                     "una por sector y en rojo con un triángulo, la marca de búsqueda de intocables "
                     "pendiente"):
            with self.subTest(fact=fact):
                self.assertIn(fact, bullet)

    def test_the_m2_check_says_the_profile_that_the_grid_does_not_resolve_is_red(self) -> None:
        """RF-013-20 (T42; H3 (4)): la comprobación manual M2 de ``tasks.md`` dice que el perfil
        «no resuelto por la rejilla» sale en rojo, con un triángulo (el ``alert`` de Blender); la M1
        sigue diciendo ámbar del borde de los sectores pendientes de la vista previa."""
        tasks = docs.read(TASKS_RELPATH)
        m2 = one_line(tasks[tasks.index("- **M2 — Perfiles de banco"):tasks.index("- **M3 — Sectores")])
        self.assertNotIn("ámbar", m2)
        self.assertIn("un perfil «no resuelto por la rejilla» en rojo, con un triángulo", m2)
        m1 = one_line(tasks[tasks.index("- **M1 — E5"):tasks.index("- **M2 — Perfiles")])
        self.assertIn("(ámbar si están pendientes)", m1)


@docs.requires_docs
class EntitiesGuideDocTest(unittest.TestCase):
    """La guía de uso de las entidades de diseño (``docs/usuario/entidades-de-diseno.md``; spec 015,
    T34) dice lo que el código hace: todo texto entre «» sale del catálogo o es un ejemplo que esta
    prueba lista, las órdenes llevan el texto de su catálogo, los datos, los parámetros y las cifras son
    los del código, y «Límites conocidos» dice lo que hoy no hace y no promete lo que la spec deja
    abierto (RNF-015-09)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = docs.read(ENTITIES_GUIDE_RELPATH)
        cls.index = QuoteIndex(catalog_texts())

    def guide_section(self, heading: str) -> str:
        return one_line(section(self.guide, heading))

    def test_every_quoted_text_is_in_the_catalog_or_is_a_listed_example(self) -> None:
        """Principio 10, RF-015-03, RF-015-26, RF-015-28 (T34): todo texto de la guía entre «» sale del
        catálogo (``messages.toml``, ``design.messages``, las órdenes y las familias de datos), con otras
        cifras y otros nombres y con lo que omite con «…», o está en :data:`ENTITY_EXAMPLES`; y todo lo de
        la lista sigue en la guía."""
        found = quotes(self.guide)
        self.assertGreater(len(found), 60)
        unknown = sorted({quote for quote in found
                          if quote not in ENTITY_EXAMPLES and not self.index.has(quote)})
        self.assertEqual(unknown, [], "textos de la guía que el catálogo no dice (cámbielos en la guía, "
                                      "o en el código si es él el que está mal)")
        self.assertEqual(sorted(set(ENTITY_EXAMPLES) - set(found)), [],
                         "ejemplos que la guía ya no cita: quítelos de ENTITY_EXAMPLES")

    def test_every_listed_example_is_not_in_the_catalog(self) -> None:
        """Un ejemplo de :data:`ENTITY_EXAMPLES` que sí está en el catálogo sobra: la lista solo tiene lo
        que no sale de él."""
        for example in ENTITY_EXAMPLES:
            with self.subTest(example=example):
                self.assertFalse(self.index.has(example))

    def test_orders_are_named_with_their_catalog_text(self) -> None:
        """RF-015-28 (plan 015 §5.3.3): la guía nombra cada orden de las entidades con el texto de su
        catálogo y dice dónde está."""
        cat = catalog.load()
        for key in ENTITY_ORDERS:
            with self.subTest(order=key):
                self.assertIn(cat.commands[key].label_es, self.guide)
        self.assertIn("Diseño ▸ Pistas y entidades ▸ Entidades ▸ Plataforma…", self.guide)

    def test_data_parameters_and_figures_are_the_code_s(self) -> None:
        """RF-015-01, RF-015-02, RF-015-10, RF-015-24, RF-015-27 (plan 015 §5.2): §17 da la ruta de cada
        rejilla y de cada tabla de las entidades, la familia de parámetros de la plataforma y cada cifra
        como las nombra el código."""
        where = inline_tokens(self.guide_section("## 17. Dónde queda cada cosa en el proyecto"))
        for family in dprov.ENTITY_FAMILIES:
            locator = dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01")
            shown = locator.replace("mi_nombre", "<nombre>").replace("v01", "<vNN>")
            with self.subTest(dataset=family.code):
                self.assertTrue(any(shown in token for token in where), shown)
        self.assertIn("des.platform.{e}.*", where)
        for figure in dprov.ENTITY_FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, where)
        parameters = inline_tokens(self.guide)
        self.assertEqual(dparams.entity_segment("PLT-001"), "plt_001")
        for token in ("PLT-001", "plt_001", "dec__plt_001"):
            with self.subTest(token=token):
                self.assertIn(token, parameters)

    def test_the_known_limits_are_told(self) -> None:
        """T34 y T47: «Lo que no hace todavía» dice los límites de **hoy**: las plataformas sin calcular sin objeto,
        lo que Esc deja a medias tras «Crear» y que «Recalcular lo obsoleto» no ve, el estado atrasado de la capa de
        QGIS, aceptar la edición de lo declarado y recalcular sin compilar antes las máscaras (T40 (c)), la entidad
        insertada que se rehace dos veces (T42 (c), C-14: dentro de la misma orden), el enlace de un polígono con su
        eje que no pasa a la versión que trae la entidad y la
        entidad traída sin su partida (T41 (e)), el diseño cuya partida es una entidad descartada (C-17), declarar una
        dependencia solo por parámetro o API (C-13), la superficie de la 014 que congelar pide y el sector pendiente
        conservador (decisiones del 15/11/2026), y el tamaño por entidad sin prometer los 16 MB: RNF-015-09 está
        resuelto en 17 MiB. **Ya no** dice (T40, hallazgos C-2, C-4 y E-3) que aceptar con motivo la edición de una
        tabla de versión no limpia «Recalcular lo obsoleto» ni que una plataforma descartada con una operación vieja
        sigue en su plan, ni (T41, C-12) que una entidad traída no se pueda calcular por la interfaz, ni que
        «Recalcular lo obsoleto» no detecte las entidades nuevas (T38, E-1): están corregidos. **Ni** (T51, T52; H3-2)
        que a veces hagan falta dos pasadas de «Recalcular lo obsoleto»: una pulsación recorre toda la cadena."""
        limits = self.guide_section("## 16. Lo que no hace todavía")
        for fact in ("Límites conocidos de esta versión",
                     "no tiene objeto en la escena",
                     "no ve lo que Esc dejó a medias", "estado atrasado",
                     "sin compilar antes las máscaras", "se rehace dos veces",
                     "no es un parámetro", "sin su partida",
                     "una entidad descartada no se puede rehacer", "solo se puede por el parámetro",
                     "la superficie de la 014 de la que parte", "sector pendiente es conservadora",
                     "unos 16 MiB", "unos 0,3 GiB", "RNF-015-09", "17 MiB"):
            with self.subTest(fact=fact):
                self.assertIn(fact, limits)
        for gone in ("no limpia «Recalcular lo obsoleto»", "sigue en el plan de «Recalcular lo obsoleto»",
                     "no detecta las entidades nuevas", "sigue pendiente de decisión",
                     "dos pasadas", "A veces hacen falta"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, limits)
        self.assertNotIn("16 MB", self.guide)

    def test_the_convergence_is_told(self) -> None:
        """T47 (hallazgos de la verificación única, T38 a T49): la guía dice lo que cambió la convergencia y el
        ingeniero de minas ve: «Calcular…» calcula una entidad traída (C-12, §10), «Cambiar parámetro…» rechaza lo que
        crear rechazaría (A-2, A-1, B-1, §11), la huella que la rejilla recorta se avisa y no se rechaza (D-1/A-7, §5),
        «Calcular» compila antes las máscaras obsoletas, con una operación propia que Esc no deshace (A-5, §5), el
        apoyo se detecta también al recalcular (C-1, §9), Esc vale mientras se pone al día la capa (F-1, §14), el
        factor de malla es de (0; 1] y un eje sobre el contorno se rechaza (D-3, D-7, §4), la abscisa 0 es donde
        entra la línea enlazada (D-8, §1) y lo que decidió Samuel (A-4, B-5, C-16, C-13)."""
        guide = one_line(self.guide)
        for fact in (
                "**Calcular…** (menú «Entidad ▾») calcula las entidades que quedan sin calcular",
                "sin escribir ningún parámetro", "detecta de nuevo aquello que se le apoya",
                "**rechaza lo que crear rechazaría**", "una superficie de apoyo que sería un ciclo",
                "no se rechaza", "los m² de huella que quedan fuera",
                "la plataforma **se calcula con la parte de dentro y no se rechaza**",
                "**Calcular** las compila antes", "una vez terminada **no se deshace** con Esc",
                "al crearla **y al recalcularla, aunque la entidad apareciera después**",
                "**Esc vale también mientras «Recalcular lo obsoleto» pone al día la capa de entidades**",
                "El factor es de **(0; 1]**", "tampoco el que discurre sobre su contorno",
                "donde la línea entra en él", "**el borde no avisa la pared que el terreno ya tenía**",
                "**solo con la otra superficie de la cantera**", "aguas arriba o a media plataforma",
                "congelar pide además esa superficie", "no hay todavía una orden de la interfaz"):
            with self.subTest(fact=fact):
                self.assertIn(fact, guide)
        self.assertEqual(guide.count("«la rejilla del proyecto recorta su huella"), 1)
        clipped = dmessages.render("des.platform_footprint_clipped", entity="Carga", area=1200.0, cells=300,
                                   x=480000.0, y=4400000.0)
        self.assertIn("la rejilla del proyecto recorta su huella", clipped)
        # El código y el mensaje que la guía cita son los reales: el rango del factor de malla.
        self.assertEqual(dparams.ENTITY_RANGES["mesh_factor"].maximum, 1.0)
        self.assertTrue(dparams.ENTITY_RANGES["mesh_factor"].min_exclusive)
        self.assertFalse(dparams.ENTITY_RANGES["mesh_factor"].max_exclusive)

    def test_the_recompute_goes_through_the_chain_in_one_order(self) -> None:
        """RF-008-26, HU-015-2 (T52; T51, hallazgos H3-2 y H3-1): la guía dice que **una pulsación** de «Recalcular lo
        obsoleto» deja al día toda la cadena (la orden vuelve a planificar sola), con Esc como siempre, lo rechazado una
        sola vez y un tope contra los bucles que se avisa con el mensaje del código; que el resumen nombra la capa de
        entidades y la declaración con palabras («la capa de entidades de V01»), y **ya no dice** «dos pasadas» ni
        «varias pasadas» ni cuenta las pasadas que antes eran tres (§11 y §16)."""
        guide = one_line(self.guide)
        changing = self.guide_section("## 11. Cambiar una entidad: obsoleto y recalcular en cascada")
        for fact in ("**una sola pulsación deja al día toda la cadena**",
                     "no hay que volver a pulsar", "vuelve a planificar sola mientras quede algo que rehacer",
                     "**Esc** vale como siempre", "sale **una vez** con su motivo y no se reintenta",
                     "tiene un **tope**", "lo que sigue obsoleto lo rehace la próxima pulsación"):
            with self.subTest(fact=fact):
                self.assertIn(fact, changing)
        for fact in ("**«la capa de entidades de V01»**", "**«las restricciones declaradas de V01»**"):
            with self.subTest(fact=fact):
                self.assertIn(fact, one_line(self.guide_section("## 5. Calcular y Crear: el resumen")))
        for gone in ("dos pasadas", "tres pasadas", "varias pasadas", "A veces hacen falta"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, guide)
        # Lo que la guía cita es lo que hace el código: la función de una vez, su resultado y el aviso del tope.
        self.assertIn("recompute_settled_steps", provenance.RECOMPUTE_API)
        self.assertEqual({"passes", "limit_reached"} - set(provenance.RecomputeOutcome.__dataclass_fields__), set())
        self.assertTrue(any(text.startswith("El recálculo se paró tras {passes} pasadas")
                            for text in i18n.load_messages().values()))
        for code, text in (("des.entity_layer_name", "la capa de entidades de V01"),
                           ("des.entity_declaration_name", "las restricciones declaradas de V01")):
            with self.subTest(code=code):
                self.assertEqual(dmessages.render(code, version="V01"), text)


@docs.requires_docs
class RecomputeCardDocTest(unittest.TestCase):
    """Las fichas de arquitectura dicen lo que cambió «Recalcular lo obsoleto» de una vez (spec 015, T52; T51,
    RF-008-26): ``core.md`` (la 008, de forma aditiva) y ``des.md`` (los nombres de lo que queda obsoleto)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.core = one_line(docs.read("docs/arquitectura/modulos/core.md"))
        cls.des = docs.read(DES_RELPATH)

    def test_core_card_names_the_settled_recompute(self) -> None:
        """RF-008-26, RF-008-27 (T52; T51): ``core.md`` nombra ``core.provenance.recompute_settled_steps`` (varias
        ejecuciones de ``recompute_steps``, volviendo a planificar entre ellas, con tope ``max_passes``),
        ``RecomputeOutcome.passes`` y ``limit_reached``, y que ``recompute_steps`` y su contrato no cambian; y todo eso
        existe."""
        for fact in ("`core.provenance.recompute_settled_steps`", "`max_passes`",
                     "`core.provenance.RecomputeOutcome.passes`", "`core.provenance.RecomputeOutcome.limit_reached`",
                     "`recompute_steps` y su contrato no cambian", "vuelve a planificar"):
            with self.subTest(fact=fact):
                self.assertIn(fact, self.core)
        settled = provenance.recompute_settled_steps
        self.assertIn("max_passes", inspect.signature(settled).parameters)
        fields = provenance.RecomputeOutcome.__dataclass_fields__
        self.assertEqual((fields["passes"].default, fields["limit_reached"].default), (1, False))

    def test_des_card_names_what_the_summary_calls_things(self) -> None:
        """RF-015-16, HU-015-2 (T52; T51, H3-1): la API de ``design.preview`` nombra ``Named`` y ``obsolete_names``
        (están en su ``__all__``) y §1.7 y §4.3, ``Obsolete.label`` y los dos mensajes que nombran la capa de
        entidades y la declaración entre lo que queda obsoleto, que existen; y el módulo de ``core`` que lo hace de
        una vez (``recompute_settled_steps``)."""
        for name in ("Named", "obsolete_names"):
            with self.subTest(name=name):
                self.assertIn(name, dpreview.__all__)
        tokens = inline_tokens(self.des)
        for token in ("Obsolete.label", "des.entity_layer_name", "des.entity_declaration_name",
                      "core.provenance.recompute_settled_steps"):
            with self.subTest(token=token):
                self.assertIn(token, tokens)
        self.assertIn("label", dpreview.Obsolete.__dataclass_fields__)
        for code in ("des.entity_layer_name", "des.entity_declaration_name"):
            with self.subTest(code=code):
                self.assertIn(code, dmessages.MESSAGES)
        self.assertNotIn("necesita **dos pasadas**", self.des)


class EntitiesChangelogTest(unittest.TestCase):
    """El ``CHANGELOG.md`` del código dice, para el ingeniero de minas y sin jerga, lo que cambió «Recalcular lo
    obsoleto» (spec 015, T52; T51, RF-008-26, H3-1 y H3-2)."""

    def test_the_changelog_says_the_recompute_goes_through_the_chain(self) -> None:
        """RF-008-26, HU-015-2 (T52): «Recalcular lo obsoleto» recorre ahora una cadena de entidades de **una vez**
        (una pulsación), con su tope; el resumen nombra «la capa de entidades» y «las restricciones declaradas»; y ya no
        dice que a veces necesite dos pasadas."""
        text = one_line(CHANGELOG_PATH.read_text(encoding="utf-8"))
        entry = text[text.index("- **Entidades de diseño paramétricas** (spec 015"):
                     text.index("- **Cantera con dos superficies** (spec 014")]
        for fact in ("**una sola pulsación** de «Recalcular lo obsoleto» recorre toda la cadena",
                     "con un tope contra los bucles", "la capa de entidades de V01",
                     "las restricciones declaradas de V01"):
            with self.subTest(fact=fact):
                self.assertIn(fact, entry)
        self.assertNotIn("dos pasadas", text)
        self.assertNotIn("pasada", entry, "la entrada de la 015 se escribe sin la jerga de las pasadas")
        changed = text[text.index("- **Procedencia** (spec 008, hecho con la spec 015"):
                       text.index("- **Formato del proyecto, versión 3**")]
        self.assertIn("recorre el plan de una vez", changed)


# --- La 016 (acopios, contrafuerte y cuerpos apoyados; su T38) --------------------------------------

SUPPORTED_GUIDE_RELPATH = "docs/usuario/acopios-y-contrafuertes.md"
SUPPORTED_TASKS_RELPATH = "specs/016-des-acopios-contrafuerte-y-cuerpos-apoyados/tasks.md"
ADR_0031_RELPATH = "docs/adr/0031-acopios-deteccion-base-y-espesor.md"
BS_RELPATH = "docs/arquitectura/interfaz/barra-superior.md"
PC_RELPATH = "docs/arquitectura/interfaz/paneles-contextuales.md"
# Las órdenes de la 016 y las de la 015 que la guía nombra con el texto de su catálogo.
SUPPORTED_ORDERS = ("geoblender.des_edit_stockpile", "geoblender.des_detect_stockpiles",
                    "geoblender.des_stockpile_candidates", "geoblender.des_remove_stockpile",
                    "geoblender.des_add_buttress", "geoblender.des_create_body",
                    "geoblender.des_entity_dependents", "geoblender.des_entity_discard",
                    "geoblender.des_entity_release_support", "geoblender.des_entity_preview",
                    "geoblender.des_export_design_grid")
# De lo que la guía de la 016 pone entre «», lo que no está en el catálogo: nombres de ejemplo y términos que la guía
# explica. La prueba exige que siga en la guía y que no haya ninguno más.
SUPPORTED_EXAMPLES: tuple[str, ...] = (
    # Lo que era la orden que pasó de Geología a «Cuerpo apoyado…» (ya no está en el catálogo).
    "Unidad por espesor sobre su apoyo…",
    # Un botón que la guía dice que **no** existe (queda como idea futura: Samuel no lo ha pedido) y la redacción que la
    # spec 0.4 escribe en RF-016-20 (el espesor de una línea 3D, en su Z o en un campo).
    "Añadir las unidades de esta detección", "su Z o un campo",
    # El cierre del 20/11/2026: la sección de las tareas donde están las decisiones, lo que contestó Samuel y cómo queda CE-016-08.
    "Decisiones de Samuel", "Sí, por defecto", "sin ejecutar con los datos originales",
    # Lo que el H3 vio en pantalla y no se arregló: dos textos con una palabra repetida (el hallazgo H3-3).
    "Detección de acopios acopios", "Plataforma Plataforma de carga (declarada)",
    # El motivo generado de un contrafuerte llamado B1 (su nombre y su código van en el mensaje del catálogo).
    "declarada por el contrafuerte B1",
    # El material de los acopios sin el campo `material` y de los candidatos convertidos (T50, S-15): el nombre que le da la
    # detección (``stockpile_store._NO_MATERIAL``).
    "sin material",
)
# Lo que dice la guía de cada umbral de la detección: el texto de su valor por defecto y su tipo, que la prueba compara
# con el código (``design.params``).
THRESHOLD_ROWS = (
    (("margin_m",), "10 m", "ADOPTADO «sin confirmar»"),
    (("crown_inner_m", "crown_outer_m"), "1 m y 3 m", "ADOPTADO «sin confirmar»"),
    (("crown_slope_deg",), "12°", "ADOPTADO «sin confirmar»"),
    (("crown_flat_min_m2",), "10 m²", "ADOPTADO «sin confirmar»"),
    (("max_residual_m",), "1 m", "ADOPTADO «sin confirmar»"),
    (("fit_rounds", "turns"), "4 y 6", "ADOPTADO «sin confirmar»"),
    (("tilt_max_deg",), "4°", "**HIPÓTESIS**"),
    (("support_quantile",), "0,6", "**HIPÓTESIS**"),
    (("open_diameter_m",), "31 m", "**HIPÓTESIS**, **no confirmado**"),  # T48 (D-4): el banco no la confirmó
    (("min_height_m",), "2 m", "ADOPTADO «sin confirmar»"),
    (("min_area_m2", "max_area_m2"), "150 m² y 20.000 m²", "ADOPTADO «sin confirmar»"),
)


def spanish_number(value: float) -> str:
    """``value`` como lo escribe la guía: sin decimales si es entero (con punto de millar desde 10.000) y con coma
    decimal si no."""
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".") if abs(value) >= 10000 else str(int(value))
    return str(value).replace(".", ",")


@docs.requires_docs
class SupportedCardDocTest(unittest.TestCase):
    """Las fichas de arquitectura dicen los datos, los parámetros, las cifras y las operaciones de la 016 (T38; plan 016
    §5.2): ``des.md`` («Datos que posee»), ``formato-proyecto.md`` (§3.3, §3.11 y §4.2) y el ADR-0031 (su fe de erratas)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.des = docs.read(DES_RELPATH)
        cls.format = docs.read(FORMAT_RELPATH)

    def test_owned_data_parameters_figures_and_operations_of_the_016(self) -> None:
        """RF-016-02, RF-016-09, RF-016-13, RF-016-17, RF-016-19, RF-016-20, RF-016-21 (plan 016 §5.2.2 y §5.2.3): «Datos que
        posee» nombra cada familia de datos de la 016, cada familia de parámetros de sus cuatro tipos, cada cifra y cada
        tipo de operación (los cinco, los dos de la detección entre ellos)."""
        owned = inline_tokens(section(self.des, "## Datos que posee"))
        for family in dprov.SUPPORTED_FAMILIES:
            shown = (raster_pattern(family.code, folder=False).removesuffix(".tif").replace("_<vNN>", "")
                     if family.extension else table_pattern(family.code).replace("_<vNN>", ""))
            with self.subTest(dataset=family.code):
                self.assertTrue(any(shown in token for token in owned), shown)
        for entity in (dparams.STOCKPILE_ENTITY, dparams.REMOVAL_ENTITY, dparams.BUTTRESS_ENTITY, dparams.BODY_ENTITY):
            prefix = entity.families[0].pattern.rsplit(".", 1)[0]
            with self.subTest(parameters=entity.kind):
                self.assertIn(f"{prefix}.*", owned)
        for figure in dprov.SUPPORTED_FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, owned)
        for op in dprov.SUPPORTED_OPERATION_TYPES:
            with self.subTest(operation=op.op_type):
                self.assertIn(op.op_type, owned)
        self.assertEqual(sorted(dprov.STOCKPILE_DETECT_TYPES),
                         ["des.stockpile_detect", "des.stockpile_detect_project"])

    def test_every_parameter_family_is_in_section_3_3(self) -> None:
        """RF-016-02, RF-016-08, RF-016-11, RF-016-17, RF-016-20 (plan 016 §5.2.2; D-1, D-2, D-3, D-9, D-21; T38):
        ``formato-proyecto.md`` §3.3 nombra **exactamente** las familias de los cuatro tipos (25, 13, 14 y 17), cada una con su
        prefijo (el último segmento solo, con su punto, vale tras la primera de su fila)."""
        found: set[str] = set()
        text = section(self.format, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados")
        for table in tables(text):
            for cells in table:
                prefix = ""
                for token in backticked(cells[0]):
                    if token.startswith("des.") and "{e}." in token:
                        prefix, last = token.rsplit(".", 1)
                        found.add(f"{prefix}.{last}")
                    elif token.startswith(".") and prefix:
                        found.add(f"{prefix}{token}")
        wanted = {family.pattern for family in dparams.SUPPORTED_FAMILIES}
        self.assertEqual([len(e.families) for e in (dparams.STOCKPILE_ENTITY, dparams.REMOVAL_ENTITY,
                                                    dparams.BUTTRESS_ENTITY, dparams.BODY_ENTITY)], [25, 13, 14, 17])
        self.assertEqual(sorted(wanted - found), [], "familias de la 016 que §3.3 no nombra")
        self.assertEqual(sorted(f for f in found - wanted if f.split(".")[1] in
                                ("stockpile", "removal", "buttress", "body")), [],
                         "una familia de la 016 que el código no tiene")

    def test_the_documented_defaults_are_the_codes(self) -> None:
        """RF-016-02, RF-016-07, RF-016-08, RF-016-17, RF-016-20 (D-1, D-2, D-3, D-9, D-21; T38): lo que §3.3 y «Datos que
        posee» dicen de los valores por defecto de la 016 —los de la detección, el factor de malla y la métrica de la retirada,
        «proteger» del contrafuerte— y de los que **no** tienen valor (el ángulo de transición, la cota de coronación y la
        distancia máxima) es lo que declara el código; los HIPÓTESIS son los de la inclinación, el cuantil y (T48) la apertura de 31 m."""
        defaults = {family.pattern.rsplit(".", 1)[1]: family.template for family in dparams.STOCKPILE_ENTITY.families}
        self.assertEqual([defaults[k].default for k in ("margin_m", "crown_inner_m", "crown_outer_m", "crown_slope_deg",
                                                        "crown_flat_min_m2", "max_residual_m", "fit_rounds", "turns",
                                                        "tilt_max_deg", "support_quantile", "open_diameter_m",
                                                        "min_height_m", "min_area_m2", "max_area_m2")],
                         [10.0, 1.0, 3.0, 12.0, 10.0, 1.0, 4, 6, 4.0, 0.6, 31.0, 2.0, 150.0, 20000.0])
        self.assertEqual({k for k, v in defaults.items() if v.kind.value == "HIPÓTESIS"},
                         {"tilt_max_deg", "support_quantile", "open_diameter_m"})  # T48 (D-4): y la apertura de 31 m, que el banco no confirmó
        removal = {family.pattern.rsplit(".", 1)[1]: family.template for family in dparams.REMOVAL_ENTITY.families}
        self.assertEqual((removal["transition_deg"].default, removal["mesh_factor"].default, removal["metric"].default),
                         (None, 1.0, "exact"))
        buttress = {family.pattern.rsplit(".", 1)[1]: family.template for family in dparams.BUTTRESS_ENTITY.families}
        self.assertEqual((buttress["crown_m"].default, buttress["protect"].default, buttress["guard_m"].default),
                         (None, True, None))
        body = {family.pattern.rsplit(".", 1)[1]: family.template for family in dparams.BODY_ENTITY.families}
        self.assertEqual((body["max_distance_m"].default, body["zero_at_edge"].default), (None, False))
        for text in (section(self.format, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados"),
                     section(self.des, "## Datos que posee")):
            with self.subTest(place=text[:30]):
                self.assertIn("HIPÓTESIS", text)
        self.assertEqual(dparams.ANTHROPIC_PRESENCE, "res.anthropic_presence_m")

    def test_tables_and_grids_of_the_016_are_in_the_format(self) -> None:
        """RF-016-02, RF-016-08, RF-016-09, RF-016-17, RF-016-20 (plan 016 §5.2.3; ADR-0031 §3; T38): §3.11 nombra las dos
        tablas de la detección (el SQL, frente al código, lo comprueba ``ProjectFormatDocTest``), la ``des_epr_`` de un
        contrafuerte con su zona y los papeles de lo que lee cada consumidor, y §4.2, las seis rejillas dispersas, con sus
        papeles."""
        tables_text = section(self.format, "### 3.11 Tablas de los módulos")
        named = inline_tokens(tables_text)
        for family in dprov.SUPPORTED_FAMILIES:
            shown = table_pattern(family.code) if not family.extension else None
            if shown is not None:
                with self.subTest(table=family.code):
                    self.assertTrue(any(shown.replace("_<vNN>", "") in token for token in named), shown)
        rasters = inline_tokens(section(self.format, "### 4.2 `rasters/` — GeoTIFF"))
        for family in dprov.SUPPORTED_FAMILIES:
            if family.extension:
                shown = raster_pattern(family.code, folder=False).removesuffix(".tif").replace("_<vNN>", "")
                with self.subTest(grid=family.code):
                    self.assertTrue(any(shown in token for token in rasters), shown)
        for role in (dprov.STOCKPILES_ROLE, dprov.STOCKPILE_CANDIDATES_ROLE, dprov.STOCKPILE_BASE_ROLE,
                     dprov.STOCKPILE_THICKNESS_ROLE, dprov.STOCKPILE_GROUND_ROLE, dprov.STOCKPILE_SURFACE_ROLE,
                     dprov.BODY_THICKNESS_ROLE, dprov.BODY_BASE_ROLE, dprov.MARKS_LAYER_ROLE,
                     dprov.REMOVED_STOCKPILE_ROLE, dprov.BODY_DATA_ROLE):
            with self.subTest(role=role):
                self.assertIn(role, named | rasters)
        self.assertIn("zone", {column.name for column in dstore.BUTTRESS_ENTITY_COLUMNS})
        self.assertEqual(len(dstore.BUTTRESS_ENTITY_COLUMNS), len(dstore.ENTITY_COLUMNS) + 1)

    def test_the_adr_0031_has_its_erratum(self) -> None:
        """RF-016-02 (ADR-0031 §2; T04 y T38): el ADR-0031 lleva al final de su §2 una fe de erratas que dice que «la misma
        operación» es el mismo algoritmo con **dos tipos de operación**, y su estado no cambia (Aceptada)."""
        adr = one_line(re.sub(r"(?m)^\s*> ?", "", docs.read(ADR_0031_RELPATH)))
        for fact in ("**Fe de erratas**", "dos tipos de operación", "des.stockpile_detect", "des.stockpile_detect_project",
                     "el mismo algoritmo y las mismas familias de datos", "no cambia la decisión ni el estado"):
            with self.subTest(fact=fact):
                self.assertIn(fact, adr)
        self.assertIn("- **Estado:** Aceptada", adr)
        self.assertLess(adr.index("Fe de erratas"), adr.index("Los datos que deja"))

    def test_the_card_says_where_the_016_is(self) -> None:
        """Definición de hecho §3.7 (T38, T50 y el cierre del 20/11/2026): la cabecera de ``des.md`` dice que la 016 está
        **cerrada** por Samuel el 20/11/2026 («Sí, por defecto»; spec 0.4) y en ``main`` y **publicada** el 20/11/2026 (código ``5e41ea8``), con las 52 tareas
        hechas (la verificación única, T39, sin pantalla; la convergencia, T41 a T52; el H3 en pantalla, T40), con su guía, y que la
        015 está **cerrada y publicada**; la API de la 016 está en §4.4 y la «API prevista» pasó a §4.5; y el «apoyo retirado», la
        fe de erratas, el borde de la rejilla, lo que no está confirmado (la apertura de 31 m) y lo que decidió Samuel están en
        §1.7."""
        head = one_line(self.des[:self.des.index("## Responsabilidad")])
        for fact in ("Desde la spec 016", "**cerrada por Samuel el 20/11/2026**", "**en `main` y publicada el 20/11/2026** (código `5e41ea8`)",
                     "con las 52 tareas hechas", "su verificación única, T39, sin pantalla", "la convergencia de la T41 a la T52",
                     "el H3 en pantalla (T40, 20/11/2026", "docs/usuario/acopios-y-contrafuertes.md",
                     "**cerrada y publicada el 18/11/2026** (código `a57b8fa`)"):
            with self.subTest(head=fact):
                self.assertIn(fact, head)
        for stale in ("implementada en `main`, sin publicar", "y en verificación", "a falta del H3 en pantalla (T40)",
                      "de la decisión de Samuel", "a falta de publicar"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head)
        self.assertNotIn("el acopio, el contrafuerte y los cuerpos apoyados de §1.7 —la 016—, §1.8", head)
        self.assertIn("### 4.4 Lo que entrega la spec 016 (R-36)", self.des)
        self.assertIn("### 4.5 API prevista (otras entradas del roadmap)", self.des)
        self.assertNotIn("### 4.4 API prevista", self.des)
        text = one_line(section(self.des, "### 1.7 Entidades paramétricas y transiciones (DIS-09, DIS-10, DIS-13…DIS-16)"))
        for fact in ("fe de erratas del ADR-0031 §2", "des.stockpile_detect_project", "**marca ha de rodear el pie**",
                     "**Un montón que toca el borde de la rejilla no sale candidato**", "P-6 no queda confirmado",
                     "74, 20 o 135 candidatos", "**«Apoyo retirado» tiene una regla más**", "no en un evento",
                     "**La M de las líneas 3D no llega al proyecto**", "`des.body_data_m`", "`_creation_steps`",
                     "`SLOW_BODY_S`", "21,10 MiB",
                     # T50: lo que cambiaron la T45 a la T49 y lo que la verificación única encontró
                     "**Por dos caminos** (T45", "`removal_resting`", "**la pared no salta con esa transición**",
                     "**Lo no retirado avisa**", "`des.removal_kept`", "`WALL_REASON_KIND`", "**solo como dependencia**",
                     "**es el único aviso del salto creado del borde del contrafuerte**", "`des.body_edge_step`",
                     "**Las líneas 3D solo vienen de una capa de líneas de rotura `gis_brk_`**", "PARAMETER_PREFIXES",
                     "`des.protect_unsupported`", "`des.body_bring_surface_lost`", "12,04 s", "los otros cuatro",
                     "ninguna orden lo calcula", "`reserves.compliance_store`, la capa que toca el proyecto, sí importa `design`",
                     # el cierre del 20/11/2026: lo que decidió Samuel
                     "**Lo que decidió Samuel de la 016**", "«Sí, por defecto»", "una excepción escrita a RF-015-09",
                     "la spec 0.4 dice «su Z o un campo»", "0,25 MiB + 0,12 MiB por hectárea", "`specs/016-…/diff-011.md`",
                     "**Cumplen la 0.4**",
                     # T53 (decisión 8 de «Para Samuel»): la excepción a RF-015-09 tolera las celdas sin dato y las avisa con su lugar
                     "se avisan con su lugar", "`des.removal_no_data`", "`des.buttress_no_data`", "`supported_edge.no_data_notice`",
                     "las dos avisan con su lugar", "y avisan con su lugar (8; el aviso lo añadió la T53)"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        for stale in ("no se retiran y no avisan", "no se avisan** (se toleran", "sin aviso con su lugar (8)"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)  # T53: era un error de la spec 0.4: la excepción a RF-015-09 sí avisa con su lugar
        row = re.search(r"^\| 016-des-acopios-contrafuerte-y-cuerpos-apoyados .*$", self.des, re.MULTILINE)
        self.assertIsNotNone(row)
        assert row is not None
        for fact in ("**cerrada** el 20/11/2026", "**publicada** el 20/11/2026 (código `5e41ea8`)", "T39", "T40",
                     "acopios-y-contrafuertes.md"):
            with self.subTest(row=fact):
                self.assertIn(fact, row.group(0))
        self.assertNotIn("implementada y en verificación", row.group(0))
        self.assertNotIn("a falta de publicar", row.group(0))


@docs.requires_docs
class SupportedGuideDocTest(unittest.TestCase):
    """La guía de uso de los acopios, el contrafuerte y los cuerpos apoyados
    (``docs/usuario/acopios-y-contrafuertes.md``; spec 016, T38) dice lo que el código hace: todo texto entre «» sale del
    catálogo o es un ejemplo que esta prueba lista, las órdenes llevan el texto de su catálogo, los datos, los umbrales y las
    cifras son los del código, y «Lo que no hace todavía» dice lo que hoy no hace y no promete lo que la spec deja abierto."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = docs.read(SUPPORTED_GUIDE_RELPATH)
        cls.index = QuoteIndex(catalog_texts())

    def guide_section(self, heading: str) -> str:
        """La sección ``heading`` de la guía en una línea y sin las marcas «> » de sus recuadros."""
        return one_line(re.sub(r"(?m)^> ?", "", section(self.guide, heading)))

    def test_every_quoted_text_is_in_the_catalog_or_is_a_listed_example(self) -> None:
        """Principio 10, RF-016-23, RF-016-25 (T38): todo texto de la guía entre «» sale del catálogo (``messages.toml``,
        ``design.messages``, las órdenes y las familias de datos), con otras cifras y otros nombres y con lo que omite con
        «…», o está en :data:`SUPPORTED_EXAMPLES`; y todo lo de la lista sigue en la guía."""
        found = quotes(self.guide)
        self.assertGreater(len(found), 20)
        unknown = sorted({quote for quote in found
                          if quote not in SUPPORTED_EXAMPLES and not self.index.has(quote)})
        self.assertEqual(unknown, [], "textos de la guía que el catálogo no dice (cámbielos en la guía, o en el código "
                                      "si es él el que está mal)")
        self.assertEqual(sorted(set(SUPPORTED_EXAMPLES) - set(found)), [],
                         "ejemplos que la guía ya no cita: quítelos de SUPPORTED_EXAMPLES")

    def test_every_listed_example_is_not_in_the_catalog(self) -> None:
        """Un ejemplo de :data:`SUPPORTED_EXAMPLES` que sí está en el catálogo sobra: la lista solo tiene lo que no sale
        de él."""
        for example in SUPPORTED_EXAMPLES:
            with self.subTest(example=example):
                self.assertFalse(self.index.has(example))

    def test_orders_are_named_with_their_catalog_text(self) -> None:
        """RF-016-25 (plan 016 §5.3.3): la guía nombra cada orden de la 016 y las de la 015 que usa con el texto de su
        catálogo y dice dónde está cada una; la «Unidad por espesor sobre su apoyo…» de Geología ya no existe."""
        cat = catalog.load()
        for key in SUPPORTED_ORDERS:
            with self.subTest(order=key):
                self.assertIn(cat.commands[key].label_es, self.guide)
        self.assertIn("Diseño ▸ Pistas y entidades ▸ Entidades", self.guide)
        self.assertNotIn("geoblender.geo_create_thickness_unit", cat.commands)
        self.assertIn("Unidad por espesor sobre su apoyo…", self.guide)  # dicho como lo que era

    def test_data_paths_parameters_and_figures_are_the_code_s(self) -> None:
        """RF-016-02, RF-016-09, RF-016-13, RF-016-17, RF-016-20, RF-016-24 (plan 016 §5.2): §17 da la ruta de cada tabla y
        de cada rejilla de la 016, las cuatro familias de parámetros y cada familia de cifras como las nombra el código."""
        where = inline_tokens(self.guide_section("## 17. Dónde queda cada cosa en el proyecto"))
        for family in dprov.SUPPORTED_FAMILIES:
            shown = (raster_pattern(family.code, folder=True) if family.extension
                     else table_pattern(family.code))
            with self.subTest(dataset=family.code):
                self.assertTrue(any(shown in token for token in where), shown)
        for entity in (dparams.STOCKPILE_ENTITY, dparams.REMOVAL_ENTITY, dparams.BUTTRESS_ENTITY, dparams.BODY_ENTITY):
            prefix = entity.families[0].pattern.rsplit(".", 1)[0]
            with self.subTest(parameters=entity.kind):
                self.assertIn(f"{prefix}.*", where)
        for figure in dprov.SUPPORTED_FIGURES:
            stem = figure.key.split("_")[0]
            with self.subTest(figure=figure.key):
                self.assertIn(f"{stem}_*", where)
        for segment in ("stk_001", "rmv_001", "btr_001", "bdy_001"):
            with self.subTest(segment=segment):
                self.assertIn(segment, one_line(self.guide))
        self.assertEqual(dparams.entity_segment("STK-001"), "stk_001")
        self.assertEqual(dparams.entity_segment("BDY-001"), "bdy_001")
        self.assertIn("res.check_stockpile_cut_m3", where)

    def test_the_thresholds_and_their_types_are_the_code_s(self) -> None:
        """RF-016-02, RF-016-07, RF-016-08 (D-3, D-17; T38): la tabla de umbrales de §5 da el valor por defecto y el tipo
        (ADOPTADO «sin confirmar», y HIPÓTESIS la inclinación máxima, el cuantil y, desde la T48, el 31 m «no confirmado») que declara
        el código, y el umbral de la huella (0,30 m, el de la 011)."""
        text = section(self.guide, "## 5. Los avisos, los rechazos y los umbrales")
        rows = {cells[0]: cells for table in tables(text) for cells in table}
        by_name = {family.pattern.rsplit(".", 1)[1]: family.template for family in dparams.STOCKPILE_ENTITY.families}
        self.assertEqual(len(THRESHOLD_ROWS), 11)
        for names, shown, kind in THRESHOLD_ROWS:
            values = [by_name[name].default for name in names]
            self.assertEqual(" y ".join(f"{spanish_number(v)}{unit}" for v, unit in zip(
                values, [{"m": " m", "deg": "°", "m2": " m²", "-": ""}[by_name[name].unit] for name in names])), shown)
            with self.subTest(thresholds=names):
                (cells,) = [c for c in rows.values() if c[1] == shown]
                self.assertEqual(cells[2], kind)
                for name in names:
                    expected = by_name[name].kind.value
                    self.assertIn(expected, kind)
        self.assertIn("0,30 m", text)
        self.assertEqual(dparams.ANTHROPIC_PRESENCE, "res.anthropic_presence_m")

    def test_the_head_says_the_guide_was_seen_on_screen_and_is_pending_review(self) -> None:
        """Definición de hecho §3.7 (T38, T50 y el cierre del 20/11/2026): el recuadro del principio dice que la guía se vio en
        pantalla el 20/11/2026 (H3, T40, con eventos simulados y sin ratón real) y está pendiente de la revisión de Samuel, que la
        verificación única (sin pantalla) ya se hizo, que Samuel aceptó las 15 decisiones y la spec quedó cerrada, lo que no se
        vio, y que la apertura de 31 m no está confirmada ni CE-016-09 medido con una persona; y lleva su fecha, su spec y su estado."""
        head = one_line(re.sub(r"(?m)^> ?", "", self.guide[:self.guide.index("En el proyecto de referencia de IMGA")]))
        for fact in ("**Fecha:** 20/11/2026", "**Spec:** 016",
                     "Visto en pantalla el 20/11/2026 (H3, T40, con eventos simulados; sin ratón real); pendiente de la revisión de Samuel",
                     "Pasó su **verificación única**, sin pantalla", "**Samuel aceptó el 20/11/2026**", "**cerrada** (0.4)",
                     "**No se vio**", "la ventana «Materiales y densidades…» con el ratón", "CE-016-08",
                     "la apertura de 31 m de los candidatos no está confirmada", "CE-016-09"):
            with self.subTest(head=fact):
                self.assertIn(fact, head)
        for stale in ("Pendiente de la revisión de Samuel; no se ha visto en pantalla", "todavía no pasó el H3 en pantalla",
                      "ni se han medido a solas los tiempos", "ni ha decidido Samuel"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head)

    def test_the_marks_surround_the_foot_and_the_edge_of_the_grid(self) -> None:
        """RF-016-02, RF-016-05, RF-016-08 (H2, T22; T05 y T08; docs/trampas.md §2): §3 dice cómo dibujar la marca (que
        **rodee el pie**: con una marca dentro del pie la detección no converge, 1,64 m de error en la base) y §5, que un
        montón que toca el borde de la rejilla no sale candidato y que lo de fuera no cuenta."""
        three = self.guide_section("## 3. Antes de empezar")
        for fact in ("Cómo dibujar la marca: que rodee el pie", "dentro** del montón", "1,64 m", "no convergió en las 6 vueltas",
                     "algo mayor que el pie del montón", "Dos marcas no se pueden solapar"):
            with self.subTest(section="3", fact=fact):
                self.assertIn(fact, three)
        five = self.guide_section("## 5. Los avisos, los rechazos y los umbrales")
        for fact in ("Los bordes de la rejilla", "toca el borde de la rejilla no sale como candidato", "unos decímetros",
                     "74, 20 o 135 candidatos", "la V10 daba **60**", "decide Samuel"):
            with self.subTest(section="5", fact=fact):
                self.assertIn(fact, five)

    def test_the_removal_chain_and_the_confirmations_are_told(self) -> None:
        """RF-016-11 a RF-016-16 (CE-016-03, CE-016-04; T38): §8 a §10 dicen la transición, lo que se apoya antes de calcular
        con su confirmación, «apoyo retirado» y cómo se lee en «Recalcular lo obsoleto», la pared con su motivo de más de
        45° y 3 m (constantes, no parámetros) y «Como plataforma» (el eje de borde a borde)."""
        removal = self.guide_section("## 8. Retirar un acopio…")
        for fact in ("sin valor por defecto", "no sube ninguna celda ni baja de la base", "aunque su corte no esté admitido",
                     "**obsoleta**", "sin registrar nada",
                     # T53 (decisión 8 de «Para Samuel»): las celdas de la huella sin dato se toleran y se avisan con su lugar
                     "no se retiran, no cuentan en el volumen y se avisan", "**hay un aviso, en ámbar,**",
                     "su área en m² y el lugar de la primera", "no impide crear la retirada"):
            with self.subTest(section="8", fact=fact):
                self.assertIn(fact, removal)
        for stale in ("no se retiran y no se avisan", "no se avisan"):
            with self.subTest(section="8", stale=stale):
                self.assertNotIn(stale, removal)  # T53: la excepción a RF-015-09 sí avisa con su lugar
        resting = self.guide_section("## 9. Lo que se apoya en el acopio, y «apoyo retirado»")
        for fact in ("una sola lista", "No se retira sin su confirmación expresa", "Confirmar lo que se le apoya y crear",
                     "espera una decisión", "también con la detección del proyecto", "con un **relleno hecho antes que la detección**",
                     "El camino de E2, paso a paso", "una detección obsoleta no se retira", "Recalcular lo obsoleto"):
            with self.subTest(section="9", fact=fact):
                self.assertIn(fact, resting)
        self.assertNotIn("no deja «apoyo retirado»", resting)  # T45: con la detección del proyecto sí lo deja
        wall = self.guide_section("## 10. La pared y «Como plataforma»")
        for fact in ("más de 45° y 3 m o más", "no son parámetros", "la pared no salta con esa transición", "es un teorema",
                     "red de seguridad", "ADOPTADO", "de borde a borde", "Como plataforma",
                     "no mide la pared de la retirada ni pide confirmación ni motivo"):
            with self.subTest(section="10", fact=fact):
                self.assertIn(fact, wall)
        self.assertNotIn("casi nunca salta", wall)  # S-18: no es «casi nunca»: no puede con la transición del plan
        self.assertEqual(dprov.DECLARING_OP_NAMES, (dprov.PLATFORM, dprov.BUTTRESS))

    def test_the_marks_the_thresholds_the_azimuth_and_the_materials_are_told(self) -> None:
        """RF-016-02, RF-016-07, RF-016-08, RF-016-09, RF-016-25 (S-13 a S-15, A-1, D-6; T50): §1 dice el sentido del azimut
        (hacia donde sube el plano), §3, que una versión que no se edita desactiva «Detectar acopios…», §4, que los catorce
        umbrales son diez y cuatro con candidatos, §4 y §6, que una marca sin material y un candidato convertido caen en «sin
        material», y §7, **bien visible**, que una unidad antrópica nueva de la 011 nace «Suelto» (T52; decisión 6 de Samuel,
        20/11/2026) y hay que revisar el estado de cada unidad de acopio (en «In situ», el acopio pesa un 23 % de más sin avisar:
        el error 67)."""
        for heading, facts in (
                ("## 1. Las palabras", ("hacia donde sube", "desde el norte de la cuadrícula en el sentido de las agujas del reloj")),
                ("## 3. Antes de empezar", ("una versión activa que ya no se edita", "**Detectar acopios…** sale también en gris")),
                ("## 4. Detectar acopios… (el diálogo, la vista previa y crear)",
                 ("Son **catorce**", "el diálogo enseña **diez**", "los otros **cuatro**", "Buscar candidatos sin marca",
                  "llamado «sin material»")),
                ("## 6. Los candidatos", ("Un candidato convertido no tiene material", "sin material")),
                ("## 7. Lo que deja una detección, y cómo se usa",
                 ("Una unidad antrópica nueva nace «Suelto»", "Revise el estado de cada unidad de acopio",
                  "sale un 23 % de más", "la columna **no avisa de nada**", "el error 67", "sigue «In situ»",
                  "queda como idea futura"))):
            text = self.guide_section(heading)
            for fact in facts:
                with self.subTest(section=heading[:5], fact=fact):
                    self.assertIn(fact, text)
        seven = section(self.guide, "## 7. Lo que deja una detección, y cómo se usa")
        self.assertRegex(seven, r"(?m)^> \*\*Una unidad antrópica nueva nace «Suelto»\.\*\*",
                         "la advertencia de «Suelto» va en un recuadro, visible")
        self.assertNotIn("nace con el estado «In situ»", seven)  # T52: ya nace «Suelto»

    def test_the_common_frame_says_what_the_four_types_do_and_do_not(self) -> None:
        """RF-015-01, 08, 10, 12, 18 y 27 con los tipos nuevos (T47, T48 y T50; S-5): §14 dice que «Cambiar parámetro…» y lo
        que sigue valen para los cinco tipos, que no admite proteger en una retirada, un cuerpo ni una detección
        (``des.protect_unsupported``), que la capa se pone al día tras «Recalcular lo obsoleto» con cualquier entidad viva y que
        traer deja las entidades sin calcular con **ninguna orden que las calcule** (y el cuerpo, con su superficie re-apuntada)."""
        text = self.guide_section("## 14. Calcular y Crear, Esc, recalcular y lo común")
        for fact in ("vale para los **cinco** tipos", "No admite proteger en una retirada, un cuerpo ni una detección",
                     "con cualquier entidad viva", "re-apunta también su superficie conocida", "«Calcular…» solo ofrece "
                     "plataformas", "**ninguna orden los calcula**"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        self.assertNotIn("traer las entidades de otra versión, congelar y reproducir— vale para los cuatro tipos", text)
        self.assertIn("des.protect_unsupported", dmessages.MESSAGES)
        self.assertIn("des.body_bring_surface_lost", dmessages.MESSAGES)

    def test_the_buttress_and_the_body_say_what_they_reject(self) -> None:
        """RF-016-17 a RF-016-22 (CE-016-05, CE-016-06, CE-016-10; T38): §11 dice la cota de coronación del ancla, el pie
        libre también en solo restauración, el pie cortado y lo que declara; y §12, la regla del espesor, lo lejano, la M
        que no llega y el aviso de lo lento."""
        buttress = self.guide_section("## 11. Contrafuerte…")
        for fact in ("la cota del ancla más próxima", "el pie no se recorta a la zona dibujada",
                     "también en las zonas de solo restauración", "No corta ninguna celda", "El pie cortado", "sin corte",
                     # T50 (S-4, C-3, C-1, C-2, C-10, S-16): lo que el código hace y la guía no decía
                     "El apoyo es solo una dependencia", "no cambia el cálculo", "Ese aviso es el único del salto creado del borde "
                     "del contrafuerte", "la zona de coronación que la rejilla recorta", "del **orden** con la otra superficie",
                     "**por debajo** de ella, **igual** a ella o una zona **sin dato**", "pulse **Recalcular lo obsoleto** antes de "
                     "**Retirar un acopio…**",
                     # T53 (decisión 8 de «Para Samuel»): las celdas de la zona sin dato se toleran y se avisan con su lugar
                     "**Las celdas de la zona sin dato** de la partida no siembran ni suben y no cuentan en el volumen",
                     "pero **las avisa**, en ámbar,", "su área en m² y el lugar de la primera", "una zona **entera** sin dato sigue "
                     "rechazándose"):
            with self.subTest(section="11", fact=fact):
                self.assertIn(fact, buttress)
        self.assertNotIn("No avisa de las celdas sin dato", buttress)  # T53: la excepción a RF-015-09 sí avisa con su lugar
        body = self.guide_section("## 12. Cuerpo apoyado…")
        for fact in ("Nunca se interpola la cota de la base", "La M de las líneas 3D no se ofrece", "más próximo",
                     "se rechaza", "8 s",
                     # T50 (S-13 a S-16, C-5, C-7, C-10, T46): lo que el código hace y la guía no decía
                     "`gis_fea_`", "`gis_brk_`", "la única que guarda la Z", "el cero promedia el dato", "cuenta como un dato más",
                     "La distancia es a los vértices", "la superficie conocida", "El escalón del borde", "renglón informativo",
                     "12,04 s"):
            with self.subTest(section="12", fact=fact):
                self.assertIn(fact, body)

    def test_the_verification_with_the_base_is_told(self) -> None:
        """RF-012-24, RF-012-30, RF-012-31 (spec 012 0.5; D-a a D-d; T36, T42 y T38): §13 dice que la base es automática (la
        menor de varias), que la ventana la nombra o dice por qué no, la tabla con «Corte de terreno» y «Corte de acopios»
        (el veredicto es el de terreno), que sin acopios todo es como antes y la limitación de la detección obsoleta."""
        text = self.guide_section("## 13. La verificación de los límites con la base de los acopios")
        for fact in ("La base es automática", "la **menor** de ellas", "o por qué no", "Corte de terreno (m³)",
                     "Corte de acopios (m³)", "el veredicto es el de terreno", "Sin acopios detectados, la tabla y los "
                     "resultados son los de siempre, bit a bit", "tampoco depende de ella",
                     "verificar otra vez", "`res.check_cut_m3`", "restando"):  # T50 (D-10)
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_known_limits_are_told(self) -> None:
        """«Lo que no hace todavía» (T38, T50 y el cierre del 20/11/2026; «Decisiones de Samuel» de ``tasks.md``) dice los límites
        de **hoy**: lo que el H3 vio en pantalla (con eventos simulados) y lo que no, lo que el H3 vio y no se arregló, el banco no
        contrastado (ni la plataforma del acopio 7 ni la transición; CE-016-08 sin ejecutar), la M de las líneas 3D, que lo que
        guarda un cuerpo grande cabe en las cifras de la 0.4, la pared que no salta con la transición del plan y que «como
        plataforma» no mide, «apoyo retirado» que no es ``REFUSED``, las unidades de la 011 a mano (que nacen «Suelto» desde la T52),
        la verificación con la detección obsoleta, «Calcular…» que solo ofrece plataformas, el apoyo del contrafuerte, el cero del
        borde, las celdas sin dato y las secciones separadas; y **no** dice que «como plataforma» esté pendiente (T41), que la tabla
        de la verificación dé el corte entero (T42), que una detección del proyecto no deje «apoyo retirado» (T45), que el H3
        esté pendiente ni que las unidades de acopio nazcan «In situ»."""
        limits = self.guide_section("## 16. Lo que no hace todavía")
        for fact in ("Se vio en pantalla el 20/11/2026", "con eventos simulados y sin ratón real", "**No se vio**",
                     "Lo que el H3 vio y no se arregló", "**no rehace nada mientras una unidad espera una decisión**",
                     "**el contador de obsoletos de la barra de estado sube**", "**la leyenda de la vista previa queda debajo del diálogo**",
                     "El banco (CE-016-08) no está contrastado", "14,6 %", "7,9 %", "sin ejecutar con los datos originales",
                     "La plataforma del acopio 7 no se reproduce", "16.816 m³",
                     "La M de las líneas 3D no llega al proyecto", "La spec 0.4 dice «su Z o un campo»",
                     "Lo que guarda un cuerpo grande cabe en las cifras de la spec 0.4", "21,10 MiB", "10,60 MiB", "2,06 MiB",
                     "0,25 MiB + 0,12 MiB por hectárea",
                     "La pared no salta con la transición que aprobó el plan", "no mide la pared ni pide confirmación ni motivo",
                     "no es `REFUSED`", "se añaden a mano", "la unidad nace «Suelto»", "no existe", "no queda obsoleta sola",
                     "no se puede probar", "de 140 a 188 ms", "12,04 s", "+2,9 s",
                     "«Calcular…» solo ofrece plataformas", "El apoyo de un contrafuerte no cambia el cálculo",
                     "el cero del borde de un cuerpo se promedia con el dato", "toleran las celdas sin dato",
                     "las avisan con su lugar", "**las dos avisan con su lugar** (RF-015-13)",
                     "no enseña «Lo que se apoya en ella»", "no está marcada como no editable"):
            with self.subTest(fact=fact):
                self.assertIn(fact, limits)
        for stale in ("sin avisar** (con 30 celdas", "el aviso con su lugar no se hace"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, limits)  # T53: era un error de la spec 0.4 y de la guía: la excepción a RF-015-09 sí avisa
        self.assertNotIn("no deja «apoyo retirado»", limits)  # T45
        for stale in ("nacen «In situ»", "(el H3 está pendiente)", "No se ha visto en pantalla", "17,7 ha", "Lo decide Samuel.",
                      "se proponen a Samuel", "Se propone dejarlo así"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, limits)  # el cierre del 20/11/2026: las decisiones ya están tomadas
        self.assertNotIn("casi nunca salta", self.guide)  # T50 (S-18)
        for gone in ("como plataforma queda pendiente", "«Como plataforma» no está cableado", "sigue dando en «Corte (m³)»",
                     "16 MB"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.guide)
        # lo que dice sobre las cifras de cada tarea es lo que mide el código: la M se rechaza con su código
        self.assertIn("des.body_data_m", dmessages.MESSAGES)

    def test_the_cells_without_data_are_told_in_the_guide_and_the_code_warns_them(self) -> None:
        """RF-015-13, RF-015-09 (excepción de la 016, spec 0.4; T53, decisión 8 de «Para Samuel», 20/11/2026): las celdas sin dato de la
        huella de una retirada y de la zona de un contrafuerte se toleran **y se avisan con su lugar**: la guía lo dice en §8, §11 y §16
        y el catálogo tiene los dos avisos (``des.removal_no_data`` y ``des.buttress_no_data``, en ámbar, con las celdas, el área y el
        lugar de la primera)."""
        for code in ("des.removal_no_data", "des.buttress_no_data"):
            with self.subTest(code=code):
                message = dmessages.MESSAGES[code]
                self.assertEqual(message.severity, "warning")
                self.assertEqual(message.count, "cells")
                for marker in ("cells", "area", "x", "y"):
                    self.assertIn("{" + marker + "}", message.es)
        for heading, fact in (("## 8. Retirar un acopio…", "hay un aviso, en ámbar,"), ("## 11. Contrafuerte…", "las avisa"),
                              ("## 16. Lo que no hace todavía", "las avisan con su lugar")):
            with self.subTest(section=heading[:5]):
                self.assertIn(fact, self.guide_section(heading))

    def test_the_cubicacion_guide_says_a_new_anthropic_unit_is_born_loose(self) -> None:
        """RF-011-11, RF-011-16 (spec 011 0.4: el diff de la 016, ``diff-011.md``; decisión 6 de «Para Samuel»; T53): la guía de la cubicación
        (§8) dice que una unidad antrópica nueva de «Materiales y densidades…» nace «Suelto» (V·ρ/K) y que se cambia a «In situ» si lo
        es, y que una natural nace «In situ» y lo ya guardado conserva su estado."""
        text = one_line(docs.read("docs/usuario/cubicacion.md"))
        for fact in ("una unidad antrópica nueva (un acopio, un escombro) nace «Suelto» (V·ρ/K); cámbiela a «In situ» si lo es",
                     "Una unidad natural nace «In situ» y lo ya guardado conserva su estado"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)


@docs.requires_docs
class SupportedStateDocTest(unittest.TestCase):
    """El índice de specs, el roadmap, el ``CHANGELOG.md`` del código, la barra superior y los paneles contextuales dicen el
    estado de la 016 tras su cierre (20/11/2026): **Cerrada** por Samuel («Sí, por defecto»; spec 0.4), en ``main`` y **publicada**
    el mismo día con ``tools/publish.py`` (código ``5e41ea8``)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.specs = docs.read(SPECS_INDEX_RELPATH)
        cls.roadmap = docs.read(ROADMAP_RELPATH)
        cls.changelog = one_line(CHANGELOG_PATH.read_text(encoding="utf-8"))
        cls.index_row = re.search(r"^\| 016 \|.*$", cls.specs, re.MULTILINE)
        cls.roadmap_row = re.search(r"^\| R-36 \|.*$", cls.roadmap, re.MULTILINE)
        cls.ledger = re.findall(r"^\| 2026-11-19 \| R-36.*$", cls.roadmap, re.MULTILINE)
        cls.ledger_close = re.findall(r"^\| 2026-11-20 \| R-36.*$", cls.roadmap, re.MULTILINE)

    def test_the_index_says_where_the_016_is(self) -> None:
        """Definición de hecho §3.7 (T38, T50 y el cierre del 20/11/2026): la fila de la 016 dice que está **Cerrada** (20/11/2026,
        por Samuel: «Sí, por defecto»; spec 0.4), **cerrada y publicada**, con sus 52 tareas (la convergencia, de la T41 a
        la T52), su guía, la verificación única y el H3 hechos, las decisiones de Samuel (con el diff de la 011 aplicado a la
        011) y que RNF-016-02 «sigue sin cumplirse con secciones muy separadas»; y ya no dice que esté «sin empezar», «en
        verificación» ni que «Cerrada» sea solo tras el H3. La fila de la 011 dice su 0.4."""
        self.assertIsNotNone(self.index_row)
        assert self.index_row is not None
        row = one_line(self.index_row.group(0))
        for fact in ("**Cerrada** (20/11/2026, por Samuel: «Sí, por defecto»; spec 0.4)", "**cerrada y publicada** el mismo día",
                     "`origin/main` = código `5e41ea8`",
                     "52 (T01–T52", "la convergencia, T41 a T52", "la documentación (T38 y T50", "docs/usuario/acopios-y-contrafuertes.md",
                     "La verificación única (T39: seis verificadores sin pantalla, 66 hallazgos", "**El H3 en pantalla (T40) se hizo el 20/11/2026**",
                     "las 15 decisiones de «Para Samuel»", "una unidad antrópica nueva de la 011 nace «Suelto»", "diff de la 011",
                     "la apertura de 31 m", "CE-016-08", "el ensayo de CE-016-09 de la sesión principal",
                     "**Sigue sin cumplirse** RNF-016-02 con secciones muy separadas (8 secciones a 200 m: 12,04 s, con aviso, que la 0.4 admite)"):
            with self.subTest(fact=fact):
                self.assertIn(fact, row)
        for stale in ("sin empezar", "40 (T01–T40)", "40 tareas", "44 (T01–T44", "50 (T01–T50", "a falta de la verificación única",
                      "a falta de publicar",
                      "RNF-016-02 cumple", "**Implementada, en verificación**", "«Cerrada» solo tras el H3 y CE-016-09",
                      "**Faltan** las medidas a solas"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, row)
        row011 = re.search(r"^\| 011 \|.*$", self.specs, re.MULTILINE)
        self.assertIsNotNone(row011)
        assert row011 is not None
        for fact in ("En implementación (0.4)", "nazca «Suelto»", "`016-…/diff-011.md`", "`51fcf3f`",
                     "publicado el 20/11/2026 con la 016"):
            with self.subTest(row011=fact):
                self.assertIn(fact, one_line(row011.group(0)))

    def test_the_roadmap_says_where_the_016_is(self) -> None:
        """Definición de hecho §3.7 (T38, T50 y el cierre del 20/11/2026): la fila de R-36 dice que está hecha en sus dos specs,
        las dos **cerradas**, y la 016 **cerrada** por Samuel el 20/11/2026 («Sí, por defecto») en ``main`` y publicada el mismo día,
        con lo medido y lo que no confirma el banco; su registro del 19/11/2026 dice lo que se hizo entonces (implementada, en
        verificación) y el del 20/11/2026, el cierre; y ya no dice «sin empezar» ni que «Cerrada» sea solo tras el H3."""
        self.assertIsNotNone(self.roadmap_row)
        assert self.roadmap_row is not None
        row = one_line(self.roadmap_row.group(0))
        for fact in ("hecha en sus dos specs, las dos **cerradas**", "**cerrada** por Samuel el 20/11/2026 («Sí, por defecto»",
                     "**publicada** el 20/11/2026 (código `5e41ea8`)", "T01 a la T37 y de la T41 a la T52",
                     "verificación única (T39) hecha sin pantalla",
                     "H3 en pantalla (T40)", "las medidas a solas", "CE-016-08", "la apertura de 31 m sigue HIPÓTESIS",
                     "diff de la 011 aplicado", "docs/usuario/acopios-y-contrafuertes.md"):
            with self.subTest(row=fact):
                self.assertIn(fact, row)
        for stale in ("sin empezar", "**«Cerrada» solo tras ellos y tras CE-016-09**", "**implementada** en `main`, sin publicar",
                      "**en verificación**", "en implementación;", "**a falta de publicar**"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, row)
        self.assertEqual(len(self.ledger_close), 1, self.ledger_close)
        close = one_line(self.ledger_close[0])
        for fact in ("Samuel cierra la spec 016", "«Sí, por defecto»", "las 15 decisiones de «Para Samuel»", "spec 0.4",
                     "diff de la 011", "la 011 pasa a su 0.4", "**cerrada, a falta de publicar**", "R-36 queda hecha en sus dos specs"):
            with self.subTest(ledger_close=fact):
                self.assertIn(fact, close)
        self.assertEqual(len(self.ledger), 1, self.ledger)
        entry = one_line(self.ledger[0])
        for fact in ("**implementada, en verificación: a falta de las medidas a solas y del H3 (T40)**",
                     "la **convergencia (de la T41 a la T50)**", "la fe de erratas del ADR-0031 §2",
                     "`reserves.compliance_store` importa `design`", "**RNF-016-02 cumple salvo con secciones muy separadas, con aviso**",
                     "12,04 s", "RNF-016-07 no cumple en el cuerpo grande", "+2,9 s", "CE-016-08", "no confirma P-6",
                     "no marca R-36 como cerrada hasta entonces"):
            with self.subTest(ledger=fact):
                self.assertIn(fact, entry)
        self.assertNotIn("RNF-016-01, 02, 03, 04 y 05 cumplen medidos", entry)  # S-11
        self.assertNotIn("RNF-016-01, 02, 03, 04 y 05 cumplen medidos", row)

    def test_the_changelog_says_what_the_016_does_and_what_it_changes(self) -> None:
        """Definición de hecho §3.7 (T38): el ``CHANGELOG.md`` del código, para el ingeniero de minas y sin jerga, dice lo
        nuevo de la 016 (detectar, candidatos, retirar con lo apoyado y «como plataforma», contrafuerte, cuerpo apoyado), las
        cifras ADOPTADO y HIPÓTESIS con su aviso (la apertura de 31 m, la inclinación máxima y el cuantil) y lo que cambia la
        verificación de la 012; y lo que **no** hace todavía."""
        start = self.changelog.index("- **Acopios, contrafuerte y cuerpos apoyados** (spec 016")
        entry = self.changelog[start:self.changelog.index("- **Entidades de diseño paramétricas** (spec 015")]
        for fact in ("cerrada el 20/11/2026: verificada sin pantalla y vista en pantalla con eventos simulados, sin ratón real",
                     "Acopio (detectar, retirar)…, "
                     "Contrafuerte… y Cuerpo apoyado…", "**Detectar acopios…**", "**La marca ha de rodear el pie del montón**",
                     "**ninguno sin filtrar**", "**una sola lista de todo lo que se le apoya**", "**Como plataforma**",
                     "**El pie no se recorta a la zona dibujada**", "**sin espesores negativos**",
                     "**La M de las líneas 3D no se admite**", "ADOPTADO «sin confirmar»", "**La inclinación máxima del plano de "
                     "base (4°) y el cuantil de apoyo (0,6) son HIPÓTESIS**", "**El diámetro de apertura de los candidatos (31 m) no "
                     "está confirmado**", "74, 20 o 135 candidatos", "**Lo que no hace todavía**",
                     # T50: lo que cambiaron la T45 a la T49 y lo que la verificación única encontró
                     "**Dos marcas solapadas se rechazan, solo ellas dos**", "**comprobando su estado**",
                     "una unidad antrópica nueva nace «Suelto»", "revise el estado de cada unidad de acopio",
                     "también si la detección es del proyecto", "**Lo que no se puede retirar avisa**",
                     "no salta en el uso normal", "es el único aviso del salto del borde", "es solo una dependencia",
                     "Las líneas 3D han de ser líneas de rotura del proyecto", "el cero se promedia con el dato",
                     "**Lo que cambia del marco de las entidades de la 015**", "«Cambiar parámetro…» vale para los cinco tipos",
                     "«Calcular…» solo ofrece plataformas", "la pared no salta con la transición del plan",
                     # la decisión 8 de «Para Samuel»: las celdas sin dato de la huella se toleran y se avisan con su lugar
                     "**Las celdas de la huella sin dato también avisan**", "y las avisan con su lugar"):
            with self.subTest(fact=fact):
                self.assertIn(fact, entry)
        self.assertNotIn("toleran celdas sin dato sin avisar", entry)
        self.assertNotIn("una unidad nueva nace «In situ»", entry)  # T52: la antrópica nace «Suelto»
        for jargon in ("RF-016", "T3", "T4", "T5", "milestone", "`des_stk_"):
            with self.subTest(jargon=jargon):
                self.assertNotIn(jargon, entry, "la entrada de la 016 se escribe sin jerga de tareas ni de ficheros")
        self.assertNotIn("casi nunca salta", entry)  # T50 (S-18)
        verification = self.changelog[self.changelog.index("- **Verificación por recinto** (spec 012, versión 0.5"):
                                      self.changelog.index("- **La comprobación de cada tarea deja fuera las pruebas pesadas "
                                                           "de la spec 016**")]
        for fact in ("no cuenta como cortar terreno", "corte de terreno** y el **corte de acopios", "automática",
                     "dice qué base usa o por qué no", "Sin acopios detectados, la verificación da exactamente lo de siempre"):
            with self.subTest(verification=fact):
                self.assertIn(fact, verification)

    def test_the_bar_and_the_context_panels_tell_the_016(self) -> None:
        """RF-016-25, RF-015-28 (BS §8.7 y PC §3.11; T35 y T38): la barra superior dice que las tres órdenes son de la 016, que
        «Cuerpo apoyado…» pasa de R-18 a R-36 (D-8) y qué pide cada diálogo; el panel contextual, lo que enseña la barra N
        de cada tipo y que «Retirar» abre «Acopio (detectar, retirar)…»."""
        bar = one_line(docs.read(BS_RELPATH))
        for fact in ("**Desde la spec 016**", "**«Cuerpo apoyado…» pasa de R-18 a R-36**", "`des_detect_stockpiles`",
                     "`des_stockpile_candidates`", "`des_remove_stockpile`", "**«Como plataforma»**", "**la M no se ofrece**",
                     "los **catorce umbrales con su valor por defecto y su tipo junto al campo**",
                     "docs/usuario/acopios-y-contrafuertes.md"):
            with self.subTest(bar=fact):
                self.assertIn(fact, bar)
        self.assertNotIn("«Acopio (detectar, retirar)…» y «Contrafuerte…» siguen en R-36", bar)
        panels = one_line(docs.read(PC_RELPATH))
        for fact in ("**Desde la 016, lo propio de cada tipo:**", "`ROW_CANDIDATES`", "`ROW_DECIDE`", "de una **retirada**",
                     "**contrafuerte**", "**cuerpo apoyado**", "«Apoyo retirado: se retiró el acopio …»",
                     "docs/usuario/acopios-y-contrafuertes.md"):
            with self.subTest(panels=fact):
                self.assertIn(fact, panels)


if __name__ == "__main__":
    unittest.main()
