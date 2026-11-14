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
dstore = import_geoblender("design.store")
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

# Las secciones de la API de la ficha ``des.md``: lo de la 013 y lo que añade la 014 (su T36). Un
# módulo puede tener fila en las dos (lo de la 014 en un módulo de la 013, como ``design.store``):
# la prueba junta sus celdas.
API_SECTIONS = ("### 4.1 Lo que entrega la spec 013 (R-33)",
                "### 4.2 Lo que entrega la spec 014 (R-34)")

# Lo que la spec 015 añade a la API pública de ``design`` mientras se construye: la ficha
# (``des.md`` §4.3, hoy «API prevista») la escribe su T34 (documentación). Cada tarea de la 015 añade
# aquí sus nombres; la T34 los lleva a la ficha (una sección «Lo que entrega la spec 015 (R-36)» que
# entra en ``API_SECTIONS``) y vacía estos dos conjuntos.
PENDING_015_API = frozenset({
    # T02: design.model, design.params y design.entities.
    "Axis", "PlatformFields", "PlatformMode", "PlatformRequest",
    "PlatformParam", "check_entity_param", "entity_key", "entity_segment", "segment_code",
    "EntityKind", "EntityRecord", "EntityState", "declared_reason", "format_code", "next_code",
    # T03: design.entities (la cadena y el registro de las entidades de una versión).
    "EntityEntry", "EntityRegistry", "ParamChange", "chain_of", "chain_tails", "check_chain",
    "find_entity", "insert_after", "insert_before", "insertion_start", "predecessor_of",
    "ref_code", "registry", "start_conflict", "successor_of", "surface_ref",
    # T04: design.provenance (los tipos de operación, los ajustes, las entradas, los parámetros y las
    # cifras de las entidades).
    "entity_operation_defs", "entity_figure_scope", "platform_figures", "supported_figures",
    "declare_figures", "platform_settings", "platform_code", "platform_values",
    "platform_request", "declare_settings", "entity_layer_settings", "settings_entities",
    "platform_inputs", "declare_inputs", "entity_layer_inputs", "platform_params",
    "declare_params",
    # T05: los tres privados de la 014 que pasan a públicos (design.quarry, design.edges y
    # design.store).
    "axis_abscissa", "seed_envelope_steps", "created_step_steps",
})
# Los módulos nuevos de la 015 que aún no tienen fila en la ficha (la T34 se la da y vacía esto).
PENDING_015_MODULES = frozenset({
    "design.entities",  # T02: EntityKind, EntityRecord, EntityState, next_code, declared_reason;
    # T03: la cadena (start_conflict, insert_after, chain_of, chain_tails) y registry
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
    """El SQL con que el código crea cada tabla de la 013 (normalizado), con el nombre de ejemplo
    ``Hoyo`` y la versión ``V01`` para las de una versión."""
    berms = dprov.dataset_locator(dprov.BERM_TABLE, "Hoyo", "V01")
    report = dprov.dataset_locator(dprov.REPORT_TABLE, "Hoyo", "V01")
    with closing(sqlite3.connect(":memory:")) as conn:
        gpkg_base.create_structure(conn)
        dprofiles.create_table(conn)
        gpkg_base.create_attribute_table(conn, berms, dstore.BERM_COLUMNS, "bermas")
        gpkg_base.create_attribute_table(conn, report, dstore.REPORT_COLUMNS, "informe")
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    wanted = (dprofiles.TABLE, berms, report)
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
        """RF-013-18, RF-013-28, RF-013-30 (plan 013 §5.2.1 y §5.2.3, D-17, D-24, D-26): §3.11 tiene
        una vez el SQL de ``des_bench_profile``, de ``des_bmt_`` (las cotas reales de las bermas) y
        de ``des_rpt_`` (el informe), el que escribe el código."""
        documented = documented_tables(section(self.text, "### 3.11 Tablas de los módulos"))
        in_code = code_tables()
        self.assertEqual(len(in_code), 3)
        for name in (dprofiles.TABLE, *(
                dprov.dataset_locator(code, "Hoyo", "V01")
                for code in (dprov.BERM_TABLE, dprov.REPORT_TABLE))):
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


if __name__ == "__main__":
    unittest.main()
