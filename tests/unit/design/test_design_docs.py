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
- la 017 (su T35, la arquitectura; la guía, el glosario, el ``CHANGELOG.md``, el roadmap y el índice son de la T35b): la ficha de ``des``
  (§4.5: los trece módulos nuevos con los nombres **reales** del código y lo que la 017 añade a los demás; §1.9; «Datos que posee»: las
  siete familias de datos, las tres de parámetros, las cifras y los cuatro tipos de operación y el de los perfiles),
  ``formato-proyecto.md`` (§3.3, §3.11 con el SQL de las siete tablas y §4.2), la barra superior (§8.7) y los paneles contextuales (§3.11).
- la 017 (su T35b: la guía de uso ``docs/usuario/pistas-y-rampas.md`` —todo texto entre «» sale del catálogo o es un ejemplo que la prueba
  lista; las cifras, los tipos y los valores por defecto de sus tablas son los del código—, el glosario, ``limites-y-restricciones.md``
  con las tres respuestas de «requiere acceso», el ``CHANGELOG.md``, el índice de specs, el roadmap, ``jobs.md`` sin el worker de la
  ruta 3D y la trampa nueva de ``docs/trampas.md``).
- la 017 (su T46b, tras la convergencia: el estado, dicho **igual** en la ficha de ``des``, el índice de specs, el roadmap y ``AGENTS.md``: T01 a T46b hechas,
  T47 y el H3 por hacer, sin cerrar; las fichas que aún decían que las pistas no existen o que «Recalcular lo obsoleto» no asienta una pista anterior a un
  relleno —H2-2, desmentido—; las etiquetas del catálogo en la barra superior; ARQ-13; las trampas con los nombres de los módulos renombrados; y la tabla
  «nombre antiguo → nuevo», la nota de M1 y las «Decisiones de Samuel» de ``tasks.md`` y ``verificacion.md`` §10).

Sin la carpeta de la documentación, se omiten (recurso ``docs``). Las pruebas del emparejado de las
citas (:class:`QuoteMatcherTest`) no la necesitan: comprueban que la regla no da falsos verdes.
"""

from __future__ import annotations

import functools
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
from tests.support.repo import EXTENSION_DIR, ROOT

design = import_geoblender("design")
dmessages = import_geoblender("design.messages")
dparams = import_geoblender("design.params")
dprofiles = import_geoblender("design.profiles")
dprov = import_geoblender("design.provenance")
dsectors = import_geoblender("design.sectors")
enlayer = import_geoblender("design.entity_layer")
dstore = import_geoblender("design.store")
dpreview = import_geoblender("design.preview")
dexport = import_geoblender("design.export")
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
                "### 4.4 Lo que entrega la spec 016 (R-36)",
                "### 4.5 Lo que entrega la spec 017 (R-40)")

# El mecanismo de la 014, la 015, la 016 y la 017 para una spec que añade API pública mientras se construye: cada tarea
# añade aquí sus nombres (y los módulos nuevos, que aún no tienen fila en la ficha) y la tarea de documentación los
# lleva a la ficha y vacía estos dos conjuntos. Vacíos desde la T34 de la 015 (la ficha, ``des.md`` §4.3, nombra todo lo
# público de ``design``), otra vez desde su T47, **desde la T38 de la 016** (``des.md`` §4.4 nombra los siete módulos
# nuevos y lo que la 016 añade a los demás) y **desde la T35 de la 017** (``des.md`` §4.5 nombra los trece módulos nuevos
# de las pistas y la accesibilidad y lo que la 017 añade a los demás); una spec posterior los usará con los suyos. El nombre
# ``PENDING_015_*`` se conserva porque otras pruebas lo importan.
PENDING_015_API: frozenset[str] = frozenset()
PENDING_015_MODULES: frozenset[str] = frozenset()


def roadprofiles():
    """``design.road_profiles`` (perezoso: ``bl`` lo importa al usarlo; la prueba, solo al comprobar la documentación de la 017)."""
    return import_geoblender("design.road_profiles")


def roadlayer():
    """``design.road_layer`` (perezoso, como :func:`roadprofiles`)."""
    return import_geoblender("design.road_layer")


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
    """El SQL con que el código crea cada tabla de la 013, la 015, la 016 y la 017 (normalizado), con el nombre de
    ejemplo ``Hoyo`` (la 015, ``Carga``; la 016, ``Acopios`` y ``Refuerzo``, el de un contrafuerte; la 017, ``Acceso`` el
    eje de una pista, ``Accesibilidad`` sus tres tablas y ``Trazado`` la capa propuesta) y la versión ``V01`` para las de
    una versión."""
    berms = dprov.dataset_locator(dprov.BERM_TABLE, "Hoyo", "V01")
    report = dprov.dataset_locator(dprov.REPORT_TABLE, "Hoyo", "V01")
    entity = dprov.dataset_locator(dprov.ENTITY_TABLE, "Carga", "V01")
    entity_report = dprov.dataset_locator(dprov.ENTITY_REPORT_TABLE, "Carga", "V01")
    entity_map = enlayer.entity_layer_table("V01")
    stockpiles = dprov.dataset_locator(dprov.STOCKPILES_TABLE, "Acopios", "V01")
    candidates = dprov.dataset_locator(dprov.STOCKPILE_CANDIDATES_TABLE, "Acopios", "V01")
    buttress = dprov.dataset_locator(dprov.ENTITY_TABLE, "Refuerzo", "V01")
    axis = dprov.dataset_locator(dprov.ROAD_AXIS_TABLE, "Acceso", "V01")
    berms_reached = dprov.dataset_locator(dprov.ACCESS_BERMS_TABLE, "Accesibilidad", "V01")
    platforms_reached = dprov.dataset_locator(dprov.ACCESS_PLATFORMS_TABLE, "Accesibilidad", "V01")
    zones_reached = dprov.dataset_locator(dprov.ACCESS_ZONES_TABLE, "Accesibilidad", "V01")
    axes_layer = roadlayer().road_layer_table("V01")
    route_layer = roadlayer().route_layer_table("V01", "Trazado")
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
        roadprofiles().create_table(conn)
        gpkg_base.create_attribute_table(conn, axis, dstore.ROAD_AXIS_COLUMNS, "eje de una pista")
        gpkg_base.create_attribute_table(conn, berms_reached, dstore.ACCESS_BERM_COLUMNS, "bermas comunicadas")
        gpkg_base.create_attribute_table(conn, platforms_reached, dstore.ACCESS_PLATFORM_COLUMNS, "plataformas comunicadas")
        gpkg_base.create_attribute_table(conn, zones_reached, dstore.ACCESS_ZONE_COLUMNS, "zonas comunicadas")
        roadlayer().create_road_layer_table(conn, axes_layer, 25830)
        roadlayer().create_route_layer_table(conn, route_layer, 25830, "Trazado")
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    wanted = (dprofiles.TABLE, berms, report, entity, entity_report, entity_map, stockpiles, candidates, buttress,
              roadprofiles().TABLE, axis, berms_reached, platforms_reached, zones_reached, axes_layer, route_layer)
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


@functools.cache
def shared_quote_index() -> QuoteIndex:
    """El índice de los textos del catálogo, una sola vez por proceso para todas las pruebas de las guías de este módulo (cada una lo
    armaba por su cuenta: ≈ 0,1 s cada vez). Nadie lo cambia: es de solo lectura."""
    return QuoteIndex(catalog_texts())


# --- Pruebas sin la documentación --------------------------------------------------------------


class QuoteMatcherTest(unittest.TestCase):
    """La regla que empareja las citas de la guía con el catálogo no da falsos verdes: lo que sale
    del catálogo pasa, con cifras y nombres de otro proyecto y con lo omitido, y lo que se cambia a
    mano, una palabra, una comilla o una frase entera, no."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = shared_quote_index()

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
        ``des_epr_`` de un contrafuerte (con su zona de coronación); y RF-017-07, RF-017-23, RF-017-24, RF-017-27 y RF-017-28
        (plan 017 §5.2.3; T35) las siete de la 017: ``des_road_profile`` (los perfiles), ``des_rdx_`` (el eje por estaciones),
        ``des_acb_``, ``des_acp_`` y ``des_acz_`` (lo comunicado), ``des_rax_`` (la capa de ejes) y ``des_rpl_`` (la capa propuesta);
        ``des_decl_`` (las restricciones declaradas) está en §3.9 (``test_constraints_docs``)."""
        documented = documented_tables(section(self.text, "### 3.11 Tablas de los módulos"))
        in_code = code_tables()
        self.assertEqual(len(in_code), 16)
        for name in (dprofiles.TABLE, roadprofiles().TABLE, *(
                dprov.dataset_locator(code, "Hoyo", "V01")
                for code in (dprov.BERM_TABLE, dprov.REPORT_TABLE)),
                *(dprov.dataset_locator(code, "Carga", "V01")
                  for code in (dprov.ENTITY_TABLE, dprov.ENTITY_REPORT_TABLE)),
                enlayer.entity_layer_table("V01"),
                dprov.dataset_locator(dprov.STOCKPILES_TABLE, "Acopios", "V01"),
                dprov.dataset_locator(dprov.STOCKPILE_CANDIDATES_TABLE, "Acopios", "V01"),
                dprov.dataset_locator(dprov.ENTITY_TABLE, "Refuerzo", "V01"),
                dprov.dataset_locator(dprov.ROAD_AXIS_TABLE, "Acceso", "V01"),
                *(dprov.dataset_locator(code, "Accesibilidad", "V01")
                  for code in (dprov.ACCESS_BERMS_TABLE, dprov.ACCESS_PLATFORMS_TABLE, dprov.ACCESS_ZONES_TABLE)),
                roadlayer().road_layer_table("V01"), roadlayer().route_layer_table("V01", "Trazado")):
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
        cls.index = shared_quote_index()

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
        cls.index = shared_quote_index()

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
        §1.7 (y desde la T35 de la 017, la «API prevista» pasó a §4.6)."""
        head = one_line(self.des[:self.des.index("## Responsabilidad")])
        for fact in ("Desde la spec 016", "**cerrada por Samuel el 20/11/2026**", "**en `main` y publicada el 20/11/2026** (código `5e41ea8`)",
                     "con las 52 tareas hechas", "su verificación única, T39, sin pantalla", "la convergencia de la T41 a la T52",
                     "el H3 en pantalla (T40, 20/11/2026", "docs/usuario/acopios-y-contrafuertes.md",
                     "**cerrada y publicada el 18/11/2026** (código `a57b8fa`)"):
            with self.subTest(head=fact):
                self.assertIn(fact, head)
        for stale in ("implementada en `main`, sin publicar", "y en verificación", "a falta del H3 en pantalla (T40)",
                      "de la decisión de Samuel"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head)
        # la 016 está publicada: su párrafo no dice «a falta de publicar» (el de la 017, que viene después, sí: lo prueba ``RoadsCardDocTest``)
        self.assertNotIn("a falta de publicar", head[:head.index("**Desde la spec 017**")])
        self.assertNotIn("el acopio, el contrafuerte y los cuerpos apoyados de §1.7 —la 016—, §1.8", head)
        self.assertIn("### 4.4 Lo que entrega la spec 016 (R-36)", self.des)
        self.assertIn("### 4.6 API prevista (otras entradas del roadmap)", self.des)  # la 017 (T35) puso su §4.5 delante
        self.assertNotIn("### 4.4 API prevista", self.des)
        self.assertNotIn("### 4.5 API prevista", self.des)
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
        cls.index = shared_quote_index()

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
                     "plataformas y pistas", "**ninguna orden los calcula**"):
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
        la verificación con la detección obsoleta, «Calcular…» que solo ofrece plataformas y pistas (desde la 017), el apoyo del contrafuerte, el cero del
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
                     "«Calcular…» solo ofrece plataformas y pistas", "El apoyo de un contrafuerte no cambia el cálculo",
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
                     "«Calcular…» solo ofrece plataformas y pistas", "la pared no salta con la transición del plan",
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


# --- La 017 (pistas y rampas; su T35: la arquitectura) --------------------------------------------------

# Las seis órdenes de la 017 con su clase de ``bl/ops/des.py`` y las tres provisionales de R-40 que desaparecen.
ROAD_COMMANDS = ("des_create_road", "des_propose_road", "des_road_access", "des_edit_road_profile",
                 "des_save_road_profile", "des_export_road")
ROAD_CLASSES = tuple(f"GEOBLENDER_OT_{name}" for name in ROAD_COMMANDS)
GONE_COMMANDS = ("des_draw_haul_road", "des_route_haul_road", "des_burn_roads")
DES_OPS_PATH = EXTENSION_DIR / "bl" / "ops" / "des.py"
# El estado de la 017 tras su cierre (Samuel, 22/11/2026), **dicho igual** en la cabecera y la fila de «Specs» de ``des.md``, en el índice de specs, en el roadmap
# y en ``AGENTS.md`` (T46b, S-8; el cierre del 22/11/2026): las tareas T01 a T52 hechas, la T36 con CE-017-10 «sin ejecutar con los datos originales», la
# verificación de lo cambiado (T47 a T49) y el H3 en pantalla (T38) con su corrección (T50 a T52). Cuando la sesión principal publique la 017, cambian
# :data:`CLOSED_017` y :data:`CLOSED_017_INDEX` («a falta de publicar») en los cinco sitios, juntos.
STATE_017 = ("con las tareas T01 a T52 hechas (el banco de Silvestre, T36, con CE-017-10 sin ejecutar con los datos originales; la verificación única, T37; "
             "la convergencia, T39 a T46b; la verificación de lo cambiado, T47 a T49; y el H3 en pantalla, T38, con su corrección, T50 a T52)")
# El cierre de la 017 —Samuel («Sí, por defecto»), la spec 0.4 y lo que falta, que es publicar—, dicho igual en cuatro de los cinco sitios; el índice de specs
# lo dice con sus propias frases (como la fila de la 016 cuando se cerró).
CLOSED_017 = "**cerrada** por Samuel el 22/11/2026 («Sí, por defecto»; spec 0.4), en `main`, **a falta de publicar**"
CLOSED_017_INDEX = ("**Cerrada** (22/11/2026, por Samuel: «Sí, por defecto»; spec 0.4)", "**cerrada, a falta de publicar**")
# Lo que decían esos cinco sitios hasta la T46b y ya no (con la T47 y el H3 por hacer, y la T36 y las anteriores como «por hacer»).
STALE_STATE_017 = ("T01 a T35b", "faltan el banco de Silvestre", "por hacer el banco de Silvestre (T36)", "por hacer **la T35b**", "T01 a T35 hechas",
                   "con las tareas T01 a T46b hechas", "por hacer la T47")
# Y lo que decían antes de que Samuel la cerrara el 22/11/2026: sin cerrar, sin publicar y con el cierre por poner, con las 19 decisiones abiertas.
STALE_OPEN_017 = ("sin publicar", "sin cerrar", "no está cerrada", "el cierre lo pone la sesión principal", "siguen abiertas", "«Cerrada» solo tras el H3 y CE-017-11",
                  "«Cerrada» solo la marca la sesión principal", "**Aprobada** (0.3", "**En implementación**", "y por hacer la T47")
# Cuántos valores tiene cada familia de parámetros de la 017 y cuáles son HIPÓTESIS.
ROAD_FAMILY_COUNTS = ((dparams.ROAD_ENTITY, 26), (dparams.ACCESS_ENTITY, 8))
ROAD_ROUTE_HYPOTHESES = {"mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m",
                         "arrival_tol_m"}
ACCESS_HYPOTHESES = {"walk_slope_pct", "walk_width_m", "min_berm_area_m2"}


def values_by_name(families: Iterable[object]) -> dict[str, object]:
    """Las plantillas de ``families`` (``ParamFamily``) por el último segmento de su clave (``des.road.{e}.mode`` → ``mode``)."""
    return {family.pattern.rsplit(".", 1)[1]: family.template for family in families}  # type: ignore[attr-defined]


@docs.requires_docs
class RoadsCardDocTest(unittest.TestCase):
    """Las fichas de arquitectura dicen los datos, los parámetros, las cifras y las operaciones de la 017 (T35; plan 017 §5.2):
    ``des.md`` («Datos que posee», §1.9, §2.4 y §4.5 con los nombres reales) y ``formato-proyecto.md`` (§3.3, §3.11 y §4.2)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.des = docs.read(DES_RELPATH)
        cls.format = docs.read(FORMAT_RELPATH)

    def test_owned_data_parameters_figures_and_operations_of_the_017(self) -> None:
        """RF-017-01, RF-017-02, RF-017-07, RF-017-23, RF-017-24, RF-017-27, RF-017-28 (plan 017 §5.2.1 a §5.2.3): «Datos que posee»
        nombra cada familia de datos de la 017 (las siete), las tres familias de parámetros (26, 8 y 15 valores), la tabla de los
        perfiles, cada cifra (las 23 de la pista y las 9 de la accesibilidad), cada tipo de operación (los cuatro, de versión, y
        el de los perfiles, de proyecto) y ya no dice que las pistas grabadas estén previstas."""
        owned = inline_tokens(section(self.des, "## Datos que posee"))
        self.assertEqual(len(dprov.ROAD_DATA_FAMILIES), 7)
        for family in dprov.ROAD_DATA_FAMILIES:
            locator = dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01")
            shown = locator.removeprefix("rasters/").removesuffix(".tif").replace("mi_nombre", "<nombre>").replace("v01", "<vNN>")
            with self.subTest(dataset=family.code):
                self.assertTrue(any(shown in token for token in owned), shown)
        self.assertIn(roadprofiles().TABLE, owned)
        for entity, count in ROAD_FAMILY_COUNTS:
            prefix = entity.families[0].pattern.rsplit(".", 1)[0]
            with self.subTest(parameters=entity.kind):
                self.assertEqual(len(entity.families), count)
                self.assertIn(f"{prefix}.*", owned)
        self.assertEqual(len(dparams.ROAD_PROFILE_FAMILIES), 15)
        self.assertIn("des.roadprofile.{p}.*", owned)
        self.assertEqual((len(dprov.ROAD_FIGURES), len(dprov.ACCESS_FIGURES)), (23, 9))
        for figure in (*dprov.ROAD_FIGURES, *dprov.ACCESS_FIGURES):
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, owned)
        self.assertEqual(tuple(op.op_type for op in dprov.ROAD_OPERATION_TYPES),
                         ("des.road", "des.road_access", "des.road_propose", "des.road_layer"))
        for op in dprov.ROAD_OPERATION_TYPES:
            with self.subTest(operation=op.op_type):
                self.assertIn(op.op_type, owned)
        self.assertIn(dprov.EDIT_ROAD_PROFILES, owned)
        self.assertEqual(dprov.ROAD_REPRODUCIBLE, ("des.road", "des.road_access", "des.road_propose"))
        self.assertNotIn("Previstas: rellenos, balsa, pistas grabadas", one_line(section(self.des, "## Datos que posee")))

    def test_every_parameter_family_of_the_017_is_in_section_3_3(self) -> None:
        """RF-017-01, RF-017-02, RF-017-07, RF-017-24, RF-017-28 (plan 017 §5.2.2; D-2, D-13, D-17; T35): ``formato-proyecto.md`` §3.3
        nombra **exactamente** las familias de la 017 (26 de la pista, 8 de la accesibilidad y 15 del perfil de pista), cada una con su
        prefijo (el último segmento solo, con su punto, vale tras la primera de su fila)."""
        found: set[str] = set()
        text = section(self.format, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados")
        for table in tables(text):
            for cells in table:
                prefix = ""
                for token in backticked(cells[0]):
                    if token.startswith("des.") and ("{e}." in token or "{p}." in token):
                        prefix, last = token.rsplit(".", 1)
                        found.add(f"{prefix}.{last}")
                    elif token.startswith(".") and prefix:
                        found.add(f"{prefix}{token}")
        wanted = {family.pattern for family in (*dparams.ROAD_FAMILIES, *dparams.ACCESS_FAMILIES, *dparams.ROAD_PROFILE_FAMILIES)}
        self.assertEqual(len(wanted), 26 + 8 + 15)
        self.assertEqual(sorted(wanted - found), [], "familias de la 017 que §3.3 no nombra")
        self.assertEqual(sorted(f for f in found - wanted if f.split(".")[1] in ("road", "access", "roadprofile")), [],
                         "una familia de la 017 que el código no tiene")

    def test_the_documented_types_and_defaults_are_the_codes(self) -> None:
        """RF-017-07, RF-017-10, RF-017-24, RF-015-08 (D-2, D-17, T01-a; T35): lo que §3.3 y «Datos que posee» dicen de los valores por
        defecto de la 017 es lo que declara el código: los ocho parámetros de la ruta y los tres umbrales de la accesibilidad son HIPÓTESIS
        **sin valor por defecto**; solo el presupuesto de estados (5.000.000) y «descartada» tienen valor en la pista, y el perfil de pista
        solo el factor de malla (1,0) y la métrica (exacta), todos los demás ADOPTADO y sin valor."""
        road = values_by_name(dparams.ROAD_ENTITY.families)
        self.assertEqual({k for k, v in road.items() if v.kind.value == "HIPÓTESIS"}, ROAD_ROUTE_HYPOTHESES)  # type: ignore[attr-defined]
        self.assertEqual({k: v.default for k, v in road.items() if v.default is not None},  # type: ignore[attr-defined]
                         {"search_budget": 5_000_000, "discarded": False})
        access = values_by_name(dparams.ACCESS_ENTITY.families)
        self.assertEqual({k for k, v in access.items() if v.kind.value == "HIPÓTESIS"}, ACCESS_HYPOTHESES)  # type: ignore[attr-defined]
        self.assertEqual({k: v.default for k, v in access.items() if v.default is not None}, {"discarded": False})  # type: ignore[attr-defined]
        profile = values_by_name(dparams.ROAD_PROFILE_FAMILIES)
        self.assertEqual({v.kind.value for v in profile.values()}, {"ADOPTADO"})  # type: ignore[attr-defined]
        self.assertEqual({k: v.default for k, v in profile.items() if v.default is not None},  # type: ignore[attr-defined]
                         {"mesh_factor": 1.0, "metric": "exact"})
        self.assertEqual(road["mode"].choices, dprov.ROAD_MODES)  # type: ignore[attr-defined]
        for text in (section(self.format, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados"),
                     section(self.des, "## Datos que posee")):
            with self.subTest(place=text[:30]):
                self.assertIn("HIPÓTESIS", text)
                self.assertIn("5.000.000", text)

    def test_tables_grids_and_roles_of_the_017_are_in_the_format(self) -> None:
        """RF-017-01, RF-017-23, RF-017-24, RF-017-25, RF-017-27, RF-017-28 (plan 017 §5.2.3; T35): §3.11 nombra las siete tablas
        (el SQL, frente al código, lo comprueba ``test_tables_as_in_the_code``) y los papeles de lo que lee cada consumidor, §4.2 la
        rejilla de lo alcanzable, y dice que la capa propuesta es la **única editable en QGIS** de las siete."""
        named = inline_tokens(section(self.format, "### 3.11 Tablas de los módulos"))
        for family in dprov.ROAD_DATA_FAMILIES:
            if not family.extension:
                shown = dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01").replace(
                    "mi_nombre", "<nombre>").replace("v01", "<vNN>")
                with self.subTest(table=family.code):
                    self.assertTrue(any(shown in token for token in named), shown)
        self.assertIn(roadprofiles().TABLE, named)
        rasters = inline_tokens(section(self.format, "### 4.2 `rasters/` — GeoTIFF"))
        self.assertIn(raster_pattern("acc", folder=False), rasters)
        for role in (dprov.ROAD_AXIS_ROLE, dprov.ROAD_LAYER_ROLE, dprov.ROUTE_LAYER_ROLE, dprov.ROAD_ACCESS_ROLE,
                     dprov.ROAD_ACCESS_BERMS_ROLE, dprov.ROAD_ACCESS_PLATFORMS_ROLE, dprov.ROAD_ACCESS_ZONES_ROLE,
                     dprov.ACCESS_ENTRIES_ROLE, dprov.ACCESS_FINAL_ROLE, dprov.ROAD_OTHER_DESIGN_ROLE):
            with self.subTest(role=role):
                self.assertIn(role, named | rasters)
        editable = [family.code for family in dprov.ROAD_DATA_FAMILIES if family.qgis_editable]
        self.assertEqual(editable, ["rpl"])
        text = one_line(section(self.format, "### 3.11 Tablas de los módulos"))
        for fact in ("**Las tablas y la rejilla de las pistas y de la accesibilidad** (spec 017", "**El esquema del proyecto no cambia**",
                     "`des_rpl_<nombre>_<vNN>` **sí es editable en QGIS**", "la única de las siete", "`des_road_profile`",
                     "la rasante a CSV"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        self.assertEqual(dexport.ROAD_EXPORTS, ("surface", "gradient", "reach"))
        self.assertEqual(len(dexport.CSV_COLUMNS), 6)
        self.assertNotIn("La comprobará R-40", self.format)  # §3.9: «requiere acceso» ya lo comprueba la accesibilidad (T18)

    def test_the_card_says_where_the_017_is_and_names_the_real_modules(self) -> None:
        """Definición de hecho §3.7 (T35 y T35b; plan 017 §5.1; los nombres que las tareas cambiaron; el cierre del 22/11/2026): la cabecera de ``des.md`` dice que
        la 017 (R-40) está **cerrada** por Samuel el 22/11/2026 («Sí, por defecto»; spec 0.4), en ``main`` y a falta de publicar (:data:`CLOSED_017`), con las tareas
        T01 a T52 hechas (:data:`STATE_017`), el H3 visto en pantalla con eventos simulados y sin ratón real, su guía de uso y sus trece módulos nuevos en §4.5; §4.5
        existe y la «API prevista» pasó a §4.6 **sin** el ``design.roads.Road`` del plan; §1.9 nombra los módulos con sus nombres **reales** (``road_gradient``, no
        ``road_grade``, que el glosario §14 prohíbe, y ``road_card``), dice lo que decidió Samuel y lo que no se vio en pantalla, y §2.4 dice que las reglas de la
        rampa las aplica ya la pista."""
        head = one_line(self.des[:self.des.index("## Responsabilidad")])
        for fact in ("**Desde la spec 017**", "pistas y rampas, R-40", "sin ADR nuevo", "trece módulos nuevos (§4.5)", CLOSED_017,
                     STATE_017, "docs/usuario/pistas-y-rampas.md", "que se vio en pantalla el 22/11/2026 con eventos simulados y sin ratón real",
                     "el ensayo de CE-017-11 de la sesión principal, que Samuel acepta"):
            with self.subTest(head=fact):
                self.assertIn(fact, head)
        for stale in (*STALE_STATE_017, *STALE_OPEN_017):  # el cierre: ya no «sin publicar», ni «no está cerrada», ni la T47 y el H3 «por hacer»
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head)
        self.assertNotIn("§1.8 en adelante", head)
        self.assertIn("### 4.5 Lo que entrega la spec 017 (R-40)", self.des)
        self.assertIn("### 4.6 API prevista (otras entradas del roadmap)", self.des)
        for stale in ("design.roads.Road", "route_3d(", "grade_profile(", "`engrave(surface, road)`"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.des)
        self.assertIsNone(re.search(r"design\.road_grade\b", self.des))
        text = one_line(section(self.des, "### 1.9 Pistas y rampas (DIS-19)"))
        for name in ("road_profiles", "road_model", "road_net", "road_route", "road_axis", "road_gradient", "road_section", "road_engrave",
                     "road_store", "road_access", "access_store", "road_layer", "road_card"):
            with self.subTest(module=name):
                self.assertIn(f"design.{name}", text)  # que existe y que su fila nombra lo público: ``ModuleCardDocTest``
        for fact in ("`RDW-001`", "`ACC-001`", "**tres modos**", "16 rumbos", "**el pasillo es una holgura y no un ancho**",
                     "**La accesibilidad no es una entidad con cadena**", "`des.road_propose`", "RF-017-19", "no declara restricciones",
                     "**Lo que no hace todavía.**", "H2-2"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        self.assertIn("la pista de la 017 (§1.9)", one_line(section(self.des, "### 2.4 Rampas")))
        row = re.search(r"^\| 017-des-pistas-y-rampas .*$", self.des, re.MULTILINE)
        self.assertIsNotNone(row)
        assert row is not None
        specs_row = one_line(row.group(0))
        for fact in ("R-40", CLOSED_017, STATE_017, "pistas-y-rampas.md"):
            with self.subTest(row=fact):
                self.assertIn(fact, specs_row)
        for stale in (*STALE_STATE_017, *STALE_OPEN_017):
            with self.subTest(row_stale=stale):
                self.assertNotIn(stale, specs_row)
        text = one_line(section(self.des, "### 1.9 Pistas y rampas (DIS-19)"))
        for fact in ("**Lo que decidió Samuel de la 017** (22/11/2026, «Sí, por defecto»", "≤ 15 s por cada 2 M celdas de la ventana", "**sin ejecutar con los datos originales**",
                     "`EngraveTest.test_b`", "`des.road_carriageway_height`", "(7) **Lo que no se vio en pantalla**", "con eventos simulados y sin ratón real"):
            with self.subTest(decided=fact):
                self.assertIn(fact, text)
        for stale in ("RNF-017-04 no se cumple ahí", "es decisión de Samuel"):  # Samuel dio la cifra el 22/11/2026: ya no queda «por decidir»
            with self.subTest(decided_stale=stale):
                self.assertNotIn(stale, text)
        self.assertIsNone(re.search(r"^\| Pistas y rampas \(R-40\) \| 1\.9 y las reglas de rampa de 2\.4 \| R-33 \|$", self.des, re.MULTILINE))

    def test_the_card_tells_what_the_017_adds_to_the_other_modules(self) -> None:
        """RF-017-01, RF-017-23, RF-017-24, RF-017-27, RF-017-28 (T35): §4.5 dice, para los trece módulos nuevos y para ``params``,
        ``provenance``, ``preview``, ``steps``, ``export``, ``reproduce``, ``entities``, ``entity_store``, ``report`` y ``store``, lo
        que la 017 añade; y que ``reserves`` importa ``design.access_store`` y no ``design.road_*``."""
        text = one_line(section(self.des, "### 4.5 Lo que entrega la spec 017 (R-40)"))
        for fact in ("`design.road_gradient`", "`design.road_card`", "`design.access_store`", "`road_compute_steps`",
                     "`des.roadprofile.{p}.*`", "`des.road_propose`", "no importa `reserves`",
                     "`reserves.compliance_store` importa `design.access_store`", "no importa `design.road_*`",
                     "`AXIS_REFERENCE`", "`RDW-001@100,5`", "`design.report.max_tangents`", "`ChainStage.ROAD_LAYER`",
                     "módulos pesados"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        owned_module = one_line(section(self.des, "## Dependencias permitidas"))
        self.assertIn("`design.access_store.accessibilities_on`", owned_module)

    def test_the_bar_and_the_context_panels_tell_the_017(self) -> None:
        """RF-017-29, RF-017-27, RF-017-28, RF-015-25, RF-015-28 (BS §8.7 y PC §3.11; T35): la barra superior dice las seis órdenes con su
        clase real (las del código y las del catálogo) y que las tres provisionales de R-40 desaparecen; los paneles contextuales, lo que
        enseña la barra N de una pista (``design.road_card``) y de una accesibilidad (``DESIGN`` con ``des_acc_``) y que esta no se trae."""
        source = DES_OPS_PATH.read_text(encoding="utf-8")
        classes = set(re.findall(r"^class (GEOBLENDER_OT_des_\w+)", source, re.MULTILINE))
        cat = catalog.load()
        bar = one_line(docs.read(BS_RELPATH))
        for name, cls in zip(ROAD_COMMANDS, ROAD_CLASSES, strict=True):
            with self.subTest(order=name):
                self.assertIn(cls, classes)
                self.assertIn(f"geoblender.{name}", cat.commands)
                self.assertIn(f"`{name}`", bar)
                self.assertIn(f"`{cls}`", bar)
        for gone in GONE_COMMANDS:
            with self.subTest(gone=gone):
                self.assertNotIn(f"geoblender.{gone}", cat.commands)
                self.assertIn(f"`{gone}`", bar)
        for fact in ("**desaparecen del catálogo**", "**Calcular**", "**Vista previa**", "«Exportar pista…» no es una operación",
                     "`des_save_road_profile`", "**el destino por cota**", "la rampa", "**tres modos**"):
            with self.subTest(bar=fact):
                self.assertIn(fact, bar)
        panels = one_line(docs.read(PC_RELPATH))
        for fact in ("**Desde la 017, lo propio de la pista y de la accesibilidad:**", "`design.road_card`", "`read_road_facts`",
                     "`read_access_facts`", "`des_acc_`", "no tiene cadena ni huella", "el objeto es `DESIGN`",
                     "no se trae a otra versión", "«Pista…»"):
            with self.subTest(panels=fact):
                self.assertIn(fact, panels)


# --- La 017 (su T35b: la guía de uso, el glosario, el CHANGELOG, el roadmap y el índice) -----------------------------------

ROAD_GUIDE_RELPATH = "docs/usuario/pistas-y-rampas.md"
GLOSSARY_RELPATH = "docs/producto/glosario.md"
LIMITS_GUIDE_RELPATH = "docs/usuario/limites-y-restricciones.md"
JOBS_RELPATH = "docs/arquitectura/modulos/jobs.md"
TRAPS_RELPATH = "docs/trampas.md"
# Las órdenes de la 017 y las del marco que la guía nombra con el texto de su catálogo.
ROAD_GUIDE_ORDERS = ("geoblender.des_create_road", "geoblender.des_propose_road", "geoblender.des_road_access",
                     "geoblender.des_edit_road_profile", "geoblender.des_export_road", "geoblender.des_entity_dependents",
                     "geoblender.des_entity_discard", "geoblender.des_entity_release_support", "geoblender.des_entity_bring",
                     "geoblender.des_entity_insert", "geoblender.des_entity_calculate", "geoblender.des_entity_preview",
                     "geoblender.des_create_platform", "geoblender.core_set_parameter", "geoblender.core_recompute_stale",
                     "geoblender.res_verify_constraints", "geoblender.core_go_to_place")
# De lo que la guía de la 017 pone entre «», lo que no está en el catálogo: nombres de ejemplo, lo que dicen las ventanas de la
# verificación de la 012 (sus textos son de ``reserves.messages``, que el emparejado de las citas no lee), lo que eran las tres
# órdenes provisionales que desaparecen y los términos que la guía explica. La prueba exige que siga en la guía y que no haya
# ninguno más.
ROAD_EXAMPLES: tuple[str, ...] = (
    # Lo que eran las tres órdenes provisionales de R-40 (ya no están en el catálogo: D-20).
    "Ruta 3D con pendiente máxima…", "Grabar las pistas en la superficie",
    # Lo que dice la ventana de la verificación de la 012 de la accesibilidad que usa (``res.verify_access_used``), con un nombre de ejemplo.
    "Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad de la cantera»",
    # Términos que la guía explica y no son un texto de la interfaz: la «opción A15» de la propiedad, los rumbos «de caballo» y la rasante de
    # «mínimo movimiento» (RF-017-19, sin código).
    "opción A15", "de caballo", "mínimo movimiento",
    # La etiqueta con que la leyenda de QGIS (``core.constraints.styles.ENTITY_OTHER_LABEL``, que no está en el catálogo de la interfaz) dibuja
    # lo que el estilo de la capa de entidades no conoce: las pistas, en las versiones nacidas con la 016 (T46; E-4).
    "Otra entidad",
)
# Los recuentos que la guía dice con palabras y que el código fija: se comprueban contra él (T46; S-14: una cifra cambiada a mano en la guía no la veía ninguna prueba).
COUNT_WORDS = {15: "quince"}
# Lo que es de quien mantiene el código y no de quien usa Geoblender: no sale en el cuerpo de la guía (T46; S-13), solo en su anexo.
JARGON = re.compile(r"\bT\d{2}b?\b|\bH3\b|\bCE-\d|\bRNF-\d|\bRF-\d|check\.py|paso `hito`|des_(?:psf|rdx|epr|prp|acc|acb|acp|acz)_|entity_surface|road_access"
                    r"|des\.road_|des\.acc_|design\.|worker|DS-\d")
ANNEX_HEADING = "## Anexo. Para quien mantiene el código"
UNIT_TEXT = {"m": "m", "%": "%", "deg": "°", "1/m": "1/m", "m2": "m²", "-": "—"}
DEFAULT_TEXT = {"mesh_factor": "1,0", "metric": "exacta"}
NO_DEFAULT = "Sin valor por defecto"


def keyed_rows(text: str) -> dict[str, list[str]]:
    """Las filas de las tablas de ``text`` por cada texto entre comillas invertidas de su primera celda (su clave)."""
    found: dict[str, list[str]] = {}
    for table in tables(text):
        for cells in table:
            for key in backticked(cells[0]):
                found[key] = cells
    return found


@docs.requires_docs
class RoadsGuideDocTest(unittest.TestCase):
    """La guía de uso de las pistas y rampas (``docs/usuario/pistas-y-rampas.md``; spec 017, T35b) dice lo que el código hace: todo
    texto entre «» sale del catálogo o es un ejemplo que esta prueba lista, las órdenes llevan el texto de su catálogo, las cifras, los
    tipos y los valores por defecto de sus tablas son los del código y «Lo que no hace todavía» dice lo que hoy no hace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = docs.read(ROAD_GUIDE_RELPATH)
        cls.index = shared_quote_index()

    def guide_section(self, heading: str) -> str:
        """La sección ``heading`` de la guía en una línea y sin las marcas «> » de sus recuadros."""
        return one_line(re.sub(r"(?m)^> ?", "", section(self.guide, heading)))

    def assert_told(self, heading: str, facts: Iterable[str]) -> None:
        """Cada hecho de ``facts`` está en la sección ``heading`` de la guía."""
        text = self.guide_section(heading)
        for fact in facts:
            with self.subTest(section=heading[:5], fact=fact):
                self.assertIn(fact, text)

    def test_every_quoted_text_is_in_the_catalog_or_is_a_listed_example(self) -> None:
        """Principio 10, RF-017-29 (T35b): todo texto de la guía entre «» sale del catálogo (``messages.toml``, ``design.messages``, las
        órdenes y las familias de datos), con otras cifras y otros nombres y con lo que omite con «…», o está en :data:`ROAD_EXAMPLES`; y
        todo lo de la lista sigue en la guía."""
        found = quotes(self.guide)
        self.assertGreater(len(found), 20)
        unknown = sorted({quote for quote in found if quote not in ROAD_EXAMPLES and not self.index.has(quote)})
        self.assertEqual(unknown, [], "textos de la guía que el catálogo no dice (cámbielos en la guía, o en el código si es él el que está mal)")
        self.assertEqual(sorted(set(ROAD_EXAMPLES) - set(found)), [], "ejemplos que la guía ya no cita: quítelos de ROAD_EXAMPLES")

    def test_every_listed_example_is_not_in_the_catalog(self) -> None:
        """Un ejemplo de :data:`ROAD_EXAMPLES` que sí está en el catálogo sobra: la lista solo tiene lo que no sale de él."""
        for example in ROAD_EXAMPLES:
            with self.subTest(example=example):
                self.assertFalse(self.index.has(example))

    def test_orders_are_named_with_their_catalog_text(self) -> None:
        """RF-017-29, RF-015-28 (D-20; T35b): la guía nombra cada orden de la 017 y las del marco que usa con el texto de su catálogo, dice
        dónde están las cinco primeras (**Diseño ▸ Pistas y entidades**, antes de «Entidades») y que las tres provisionales de R-40 ya no
        existen."""
        cat = catalog.load()
        for key in ROAD_GUIDE_ORDERS:
            with self.subTest(order=key):
                self.assertIn(cat.commands[key].label_es, self.guide)
        self.assertIn("Diseño ▸ Pistas y entidades", self.guide)
        for gone in GONE_COMMANDS:
            with self.subTest(gone=gone):
                self.assertNotIn(f"geoblender.{gone}", cat.commands)
        for was in ("«Pista»", "Ruta 3D con pendiente máxima…", "Grabar las pistas en la superficie"):
            with self.subTest(was=was):
                self.assertIn(was, one_line(self.guide))  # dichas como lo que eran

    def test_the_values_their_types_and_defaults_are_the_code_s(self) -> None:
        """RF-017-07, RF-017-10, RF-017-24, RF-008-01 (D-2, D-10, D-11, D-17; T35b): las tablas de §4 y §6 dan de cada valor del perfil de pista
        (los 15), de la ruta (los 8 y el presupuesto de estados) y de la accesibilidad (los 3 umbrales) su unidad, su tipo (ADOPTADO o
        HIPÓTESIS) y su valor por defecto **como los declara el código**: los ocho de la ruta y los tres umbrales son HIPÓTESIS sin valor, el
        presupuesto, 5.000.000 ADOPTADO, y el perfil, ADOPTADO sin valor salvo el factor de malla (1,0) y la métrica (exacta)."""
        profile_rows = keyed_rows(section(self.guide, "## 4. Perfil de pista…"))
        value_rows = keyed_rows(section(self.guide, "## 6. Las cifras y su tipo"))
        wanted = (
            [(profile_rows, family) for family in dparams.ROAD_PROFILE_FAMILIES]
            + [(value_rows, family) for family in dparams.ROAD_ENTITY.families
               if family.pattern.rsplit(".", 1)[1] in ROAD_ROUTE_HYPOTHESES | {"search_budget"}]
            + [(value_rows, family) for family in dparams.ACCESS_ENTITY.families if family.pattern.rsplit(".", 1)[1] in ACCESS_HYPOTHESES])
        self.assertEqual(len(wanted), 15 + 9 + 3)
        for rows, family in wanted:
            key, template = family.pattern.rsplit(".", 1)[1], family.template
            with self.subTest(value=key):
                self.assertIn(key, rows, f"la guía no tiene la fila de «{key}»")
                cells = rows[key]
                self.assertEqual(cells[1], UNIT_TEXT[template.unit])
                self.assertEqual(cells[2], template.kind.value)
                expected = (NO_DEFAULT if template.default is None
                            else DEFAULT_TEXT.get(key) or spanish_number(template.default))  # type: ignore[arg-type]
                self.assertEqual(cells[3], expected)
        self.assertEqual({k for k, v in values_by_name(dparams.ROAD_PROFILE_FAMILIES).items() if v.default is not None}, {"mesh_factor", "metric"})  # type: ignore[attr-defined]
        self.assertEqual(len(dprov.ROAD_MODES), 3)
        self.assertEqual(roadprofiles().derived.__name__, "derived")

    def test_the_derived_values_of_the_example_profile_are_the_code_s(self) -> None:
        """RF-017-08 (T35b): el ejemplo de §4 —vehículo de 3,5 m, factor 3, arcén 0 m, caballón 1 m y pd 10 % (el del proyecto de referencia)— da
        la calzada de 10,5 m, la sección de 11,5 m, la semianchura de 5,75 m y 300 m para salvar 30 m de desnivel, como ``derived``."""
        profile = roadprofiles().RoadProfile("pista_principal", "PISTA_PRINCIPAL", 3.5, 3.0, 0.0, 1.0, 10.0, 1.0, 10.0, 20.0, 12.0, 60.0, 35.0,
                                             60.0, "Pista de acceso")
        derived = roadprofiles().derived(profile)
        self.assertEqual((derived.carriageway_m, derived.section_m, derived.half_width_m, derived.min_length_m(30.0)), (10.5, 11.5, 5.75, 300.0))
        text = self.guide_section("## 4. Perfil de pista…")
        for fact in ("**10,5 m**", "**11,5 m**", "**5,75 m**", "**300 m**", "el del proyecto de referencia de IMGA", "no es un valor por defecto"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_counts_the_guide_says_in_words_are_the_code_s(self) -> None:
        """RF-017-07, RF-017-10, RF-017-23, RF-017-24, RF-017-04 (T46; S-14): los recuentos que la guía dice —los **quince** valores del perfil, las **23** cifras de la pista y
        las **9** de la accesibilidad, los **16** rumbos y que el caballón es una anchura **sin altura**— son los del código, **en cada sitio donde los dice** (cuatro de las
        trece mutaciones de la verificación independiente de la documentación sobrevivían: nadie fijaba la cifra de una frase)."""
        profile, road, access = len(dparams.ROAD_PROFILE_FAMILIES), len(dprov.ROAD_FIGURES), len(dprov.ACCESS_FIGURES)
        self.assertEqual((profile, road, access), (15, 23, 9))
        words = COUNT_WORDS[profile]
        headings = self.guide[:self.guide.index("## 1. Las palabras")]
        self.assertIn(f"**{road_net().HEADING_COUNT} rumbos**", one_line(headings), "la presentación dice con cuántos rumbos se busca la ruta")
        self.assertIn(f"**{words} valores**", self.guide_section("## 1. Las palabras"))
        self.assertIn(f"**{words} valores**", self.guide_section("## 4. Perfil de pista…"))
        six = self.guide_section("## 6. Las cifras y su tipo")
        self.assertIn(f"las **{road}** de la pista", six)
        self.assertIn(f"las **{access}** de la accesibilidad", six)
        self.assertIn(f"las **{road} cifras** de §6", self.guide_section("## 7. Calcular, confirmar y crear"))
        self.assertIn(f"{road_net().HEADING_COUNT} rumbos", self.guide_section("## 1. Las palabras"))
        self.assertIn(f"**{road_net().HEADING_COUNT} rumbos**", self.guide_section("## 8. Si no hay ruta, y el presupuesto de estados"))
        self.assertIn(f"**{road_net().HEADING_COUNT} rumbos**", self.guide_section("## 5. Pista…: los tres modos"))
        for place, fact in (("## 1. Las palabras", "como una anchura sin altura"), ("## 4. Perfil de pista…", "una anchura, sin altura")):
            with self.subTest(berm=place):
                self.assertIn(fact, self.guide_section(place))
        parameters = inspect.signature(import_geoblender("design.road_section").section_steps).parameters
        self.assertIn("berm_m", parameters)
        self.assertEqual([name for name in parameters if "berm" in name and "height" in name], [], "el caballón del código es una anchura: no tiene altura")

    def test_the_body_of_the_guide_has_no_development_jargon(self) -> None:
        """Definición de hecho §3.7 (T46; S-13): la guía la lee un ingeniero de minas que no conoce el código: ni el principio, ni el cuerpo hasta §15 llevan el nombre de una
        tarea, de un criterio o de un requisito, ``check.py``, el paso ``hito``, un decorado de la base de datos (``des_psf_``, ``des_rdx_``…), un papel de lo que lee una orden ni el nombre
        técnico de una cifra; todo eso va **al anexo** («Para quien mantiene el código»), que existe y dice dónde está cada dato. Las dos capas que se ven en QGIS sí se nombran."""
        end = self.guide.index(ANNEX_HEADING)
        body = self.guide[:end]
        found = sorted({match.group(0) for match in JARGON.finditer(body)})
        self.assertEqual(found, [], "jerga de desarrollo en el cuerpo de la guía: va al anexo")
        self.assertIn("des_rax_<vNN>", body)
        self.assertIn("des_rpl_<nombre>_<vNN>", body)
        self.assertGreater(len(self.guide[end:]), 1500)

    def test_data_paths_parameters_and_figures_are_the_code_s(self) -> None:
        """RF-017-01, RF-017-23, RF-017-24, RF-017-27, RF-017-28 (plan 017 §5.2; T35b, T46): el anexo da la ruta de cada tabla y de cada rejilla de la 017
        (las siete), la tabla de los perfiles, las tres familias de parámetros, cada familia de cifras como las nombra el código y los
        cuatro tipos de operación, y dice cuál es la única capa que se edita en QGIS."""
        text = self.guide_section(ANNEX_HEADING)
        where = inline_tokens(section(self.guide, ANNEX_HEADING))
        self.assertEqual(len(dprov.ROAD_DATA_FAMILIES), 7)
        for family in dprov.ROAD_DATA_FAMILIES:
            shown = dprov.dataset_locator(family.code, "Mi nombre" if family.named else "", "V01").replace(
                "mi_nombre", "<nombre>").replace("v01", "<vNN>")
            with self.subTest(dataset=family.code):
                self.assertTrue(any(shown in token for token in where), shown)
        for name in (roadprofiles().TABLE, dparams.ROAD_ENTITY.families[0].pattern.rsplit(".", 1)[0] + ".*",
                     dparams.ACCESS_ENTITY.families[0].pattern.rsplit(".", 1)[0] + ".*", "des.roadprofile.{p}.*"):
            with self.subTest(name=name):
                self.assertIn(name, where)
        self.assertEqual({figure.key.split("_")[0] for figure in dprov.ROAD_FIGURES}, {"des.road"})
        self.assertEqual({figure.key.split("_")[0] for figure in dprov.ACCESS_FIGURES}, {"des.acc"})
        for token in ("des.road_*", "des.acc_*", "rdw_001", "acc_001"):
            with self.subTest(token=token):
                self.assertIn(token, text)
        for op in dprov.ROAD_OPERATION_TYPES:
            with self.subTest(operation=op.op_type):
                self.assertIn(op.op_type, where)
        self.assertIn(dprov.EDIT_ROAD_PROFILES, where)
        self.assertEqual(dparams.entity_segment("RDW-001"), "rdw_001")
        self.assertEqual(dparams.entity_segment("ACC-001"), "acc_001")
        self.assertEqual([family.code for family in dprov.ROAD_DATA_FAMILIES if family.qgis_editable], ["rpl"])
        self.assertIn("la única que se edita en QGIS", text)

    def test_the_head_says_it_is_closed_seen_on_screen_and_pending_review(self) -> None:
        """Definición de hecho §3.7 (T35b, T46; S-13; el cierre del 22/11/2026): el recuadro del principio dice, **sin jerga de tareas ni de criterios**, que la
        017 está **cerrada** por Samuel el 22/11/2026 (spec 0.4), en ``main`` y a falta de publicar, que la guía está **pendiente de la revisión de Samuel**,
        que se **vio en pantalla** el 22/11/2026 con eventos simulados y sin ratón real, que **aún no se contrastó con el proyecto de referencia**, que Samuel
        aceptó las 19 decisiones, lo que se probó sin pantalla, lo que **no se vio** y lo que falta (los datos originales del proyecto de referencia y el ensayo
        de los 20 minutos con las manos de una persona); y lleva su fecha y su spec."""
        head = one_line(re.sub(r"(?m)^> ?", "", self.guide[:self.guide.index("## 1. Las palabras")]))
        for fact in ("**Fecha:** 22/11/2026", "**Spec:** 017", "**Cerrada** por Samuel el 22/11/2026 (spec 0.4)", "**en `main`, a falta de publicar**",
                     "**pendiente de la revisión de Samuel**", "**Vista en pantalla el 22/11/2026, con eventos simulados y sin ratón real**",
                     "**aún no contrastada con el proyecto de referencia**", "sin su interfaz", "**Se vio también en pantalla**", "**Samuel aceptó el 22/11/2026**",
                     "las 19 decisiones", "**No se vio**", "los datos originales", "608 m", "136,5 m", "en menos de 20 minutos"):
            with self.subTest(head=fact):
                self.assertIn(fact, head)
        for stale in ("Visto en pantalla", "**Hecha en `main`, sin publicar**", "**Aún no se ha visto en pantalla ni contrastado con el proyecto de referencia**",
                      "sin publicar", "ya publicada", "falta `tasks.md`", "Silvestre", "verificación única"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, head)
        self.assertIsNone(JARGON.search(head), "el recuadro del principio se escribe sin jerga de tareas ni de criterios")

    def test_the_words_and_the_scenarios_are_told(self) -> None:
        """RF-017-02, RF-017-09, RF-017-11 (D-8; spec §13; T35b): §1 define el rumbo de avance (que no es el rumbo geológico), la rasante (el
        perfil de cotas, con su pendiente), el pasillo (una holgura y no un ancho), el presupuesto de estados, la rampa y la accesibilidad; §2
        recorre E1 a E5, y §3 dice qué hay que tener antes."""
        self.assert_told("## 1. Las palabras", ("**Rumbo de avance**", "no es el rumbo geológico", "**Rasante**", "perfil de cotas",
                                                "**Pendiente de la rasante**", "**Pasillo**", "una holgura y no un ancho",
                                                "**Presupuesto de estados**", "**Rampa**", "**Accesibilidad**", "**Ramal**", "**Perfil de pista**"))
        two = self.guide_section("## 2. El trabajo de un vistazo")
        for scenario in ("E1", "E2", "E3", "E4", "E5"):
            with self.subTest(scenario=scenario):
                self.assertIn(f"| {scenario} ·", two)
        self.assert_told("## 3. Antes de empezar", ("una versión activa que se pueda editar", "Las capas solo se leen y nunca se modifican",
                                                    "las máscaras de la versión", "la búsqueda de intocables", "se rechaza antes de escribir nada"))

    def test_the_three_modes_the_levels_and_the_start_surface_are_told(self) -> None:
        """RF-017-02, RF-017-03, RF-017-05, RF-017-18, RF-017-04 (D-4, D-13; T35b): §5 dice los tres modos con lo que pide cada uno, los destinos
        (un punto, una plataforma y una cota con su zona, que es la rampa), el origen en el eje de otra pista, las cotas de inicio y de fin con
        su origen, la partida (después de los rellenos) y que «eje 3D» no corrige la línea."""
        self.assert_told("## 5. Pista…: los tres modos", (
            "**Trazar**", "**Sobre un eje**", "**Eje 3D**", "16 rumbos", "la línea no se corrige", "una capa de líneas de rotura del proyecto",
            "la que deja «Proponer el trazado…»", "**El eje de otra pista**", "a una abscisa", "**Una plataforma**", "**Una cota**",
            "es la rampa", "la tolerancia de llegada", "después de los rellenos", "la superficie de explotación", "**Se apoya en**",
            "una cota que usted escribe queda anotada como decidida por usted", "nunca modifica", "la superficie de partida y la capa",
            "no llega al fondo"))
        self.assertEqual(dprov.ROAD_MODES, ("trace", "on_axis", "axis_3d"))
        self.assertEqual(road_net().HEADING_COUNT, 16)

    def test_the_confirmations_are_told(self) -> None:
        """RF-017-17, RF-017-22, RF-017-23, RF-017-13, RF-017-06, RF-017-04, RF-017-10 (D-6; T35b, T46; S-1, S-2, S-3, A-6, B-3, B-5, C-3): §7 dice lo que enseña **Calcular** sin escribir
        nada —**el corte y el relleno de la sección, los del borde y el neto en líneas distintas y la desviación máxima del eje**—, las 23 cifras, los avisos con su lugar (la
        afección a las zonas «preferible no afectar» cuenta el peso 1 y no el ruido de 10⁻⁹ m) y las dos confirmaciones: la pendiente media por encima de pm (con un motivo que queda
        registrado) y la calzada que no queda en su rasante (sin campo de motivo; la altura máxima se mide en **cada celda de la calzada**, no solo en el eje, y solo en «Trazar»);
        lo que se rechaza (el mismo nodo, el paso de cota diminuto, un ciclo); y lo que hace **Crear**."""
        self.assert_told("## 7. Calcular, confirmar y crear", (
            "no escribe nada", "23 cifras", "**Confirmar y crear**", "la pendiente media", "un motivo, que queda registrado", "con quién y cuándo",
            "no se crea sin su confirmación expresa", "sin campo de motivo", "una calzada con escalones o huecos no es una pista",
            "una sola transacción", "no declara ninguna restricción", "pulse **Calcular** otra vez", "las dos capas", "Esc",
            "el corte y el relleno **de la sección, los del borde y el neto de los dos**, cada cosa en su línea", "**la desviación máxima del eje**",
            "no es una de las 23 cifras", "«Desviación máxima del eje respecto a la ruta: …»", "**de cualquier peso, el 1 incluido**",
            "más de 10⁻⁹ m", "una pista que sigue el terreno no afecta a nada",
            "**en cada celda de la calzada**", "no solo en el eje", "en «Sobre un eje» y «Eje 3D», que no tienen ruta, no hay altura máxima",
            "el desmonte o el terraplén del eje pasa de la altura máxima",
            "caen en el mismo nodo de la malla de la ruta", "un paso de cota demasiado pequeño", "un ciclo",
            "el presupuesto de estados es más del doble"))
        for code in ("des.road_mean_unconfirmed", "des.road_mean_reason", "des.road_carriageway_unconfirmed", "des.road_mean_gradient",
                     "des.road_carriageway_masks"):
            with self.subTest(code=code):
                self.assertIn(code, dmessages.MESSAGES)
        self.assertEqual(len(dprov.ROAD_FIGURES), 23)

    def test_the_corridor_the_budget_and_the_causes_are_told(self) -> None:
        """RF-017-09, RF-017-10, RF-017-12 (D-10, D-23, S-1; T35b): §8 dice que el pasillo es una holgura y no un ancho (con las cifras medidas), las
        tres causas de «sin ruta», lo que dice el rechazo del presupuesto de estados agotado (que **no significa que no haya ruta**) y qué hacer;
        con el presupuesto de 5.000.000 (ADOPTADO)."""
        self.assert_told("## 8. Si no hay ruta, y el presupuesto de estados", (
            "el pasillo es una holgura y no un ancho", "21.978 a 31.856 nodos", "5.640", "**tres causas**", "el origen no es alcanzable",
            "el pasillo no contiene ninguna ruta", "se agotó el presupuesto de estados", "5.000.000", "no significa que no haya ruta",
            "reduzca la holgura del pasillo", "suba el presupuesto", "no se relaja ningún límite", "el tramo limitante", "56,0 s", "62,9 s",
            "la misma ruta, bit a bit"))
        self.assertEqual({cause.value for cause in road_model().NoRouteCause},
                         {"des.road_no_route_network", "des.road_no_route_corridor", "des.road_budget"})
        self.assertIn("no significa que no haya ruta", dmessages.MESSAGES["des.road_budget"].es)
        self.assertEqual(road_model().DEFAULT_SEARCH_BUDGET, 5_000_000)

    def test_the_rejections_before_the_search_and_the_memory_of_the_budget_are_told(self) -> None:
        """RF-017-10, RF-017-12, RF-017-04, RNF-017-02, RNF-017-06, RNF-017-07 (T41, T46; B-2, B-3, B-5, B-11): §8 dice los tres rechazos de antes de buscar (la cota que no cabe en lo que
        la altura máxima deja en su nodo, el origen y el destino en el mismo nodo y el paso de cota diminuto, con **sus cifras, las del código**: 2.000 niveles a cada lado y 0,007 m para 14
        m de altura), que el rechazo del presupuesto dice los estados **explorados** (los vistos) y la memoria de la búsqueda (140 bytes por estado, el aviso desde el doble del
        presupuesto por defecto, ≈ 2,6 GiB con 20 millones, hasta 10⁹)."""
        model = road_model()
        self.assertEqual((model.MAX_LEVELS, model.ROUTE_STATE_BYTES, model.BUDGET_NOTICE_STATES, model.min_level_step_m(14.0)), (2000, 140, 10_000_000, 0.007))
        self.assertEqual(round(model.budget_memory_gib(20_000_000) or 0.0, 1), 2.6)
        self.assertIsNone(model.budget_memory_gib(model.BUDGET_NOTICE_STATES))
        for code in ("des.road_level_beyond_height", "des.road_same_node", "des.road_level_step_small", "des.road_budget_memory"):
            with self.subTest(code=code):
                self.assertIn(code, dmessages.MESSAGES)
        self.assertIn("{seen} estados explorados", dmessages.MESSAGES["des.road_budget"].es)
        self.assert_told("## 8. Si no hay ruta, y el presupuesto de estados", (
            "**antes de buscar**", "queda fuera de lo que la altura máxima de desmonte y terraplén deja a la ruta en su nodo",
            "caen en el mismo nodo de la malla de la ruta", "más de 2.000 niveles a cada lado", "menos de 0,007 m",
            "los estados **explorados**", "unos 140 bytes", "2,6 GiB", "más del doble del de por defecto", "10⁹", "se puede crear igualmente"))
        self.assert_told("## 6. Las cifras y su tipo", (f"como mucho {model.MAX_LEVELS:,}".replace(",", ".") + " a cada lado", f"unos {model.ROUTE_STATE_BYTES} bytes"))

    def test_the_proposal_and_the_exports_are_told(self) -> None:
        """RF-017-27, RF-017-28 (D-19, H-9; T35b): §9 dice que «Proponer el trazado…» deja una capa de líneas con Z editable en QGIS, que no es una
        entidad ni cambia ninguna superficie, que el aviso de la media no pide confirmar y que editar su geometría **o un campo** deja obsoleta la
        pista que la usa; y §12, la capa de ejes (no editable, con estilo por clase), la barra N, la vista previa y «Exportar pista…» (la superficie
        y lo alcanzable a GeoTIFF y la rasante a CSV con sus seis columnas, sin escribir en el proyecto)."""
        self.assert_told("## 9. Proponer el trazado…", ("capa de líneas con Z", "editable en QGIS", "no cambia ninguna superficie", "no es una entidad",
                                                        "se crea sin confirmación", "también si edita un campo", "es solo un aviso"))
        self.assert_told("## 12. Lo que se ve, lo que se exporta y lo que llega a QGIS", (
            "capa de ejes de pistas", "no se edita a mano", "estilo por clase", "barra N", "**Vista previa**", "**Ir a**", "GeoTIFF", "CSV",
            "BOM de UTF-8", "separado por «;»", "CRLF", "coma decimal", "no es una operación", "también con el proyecto en solo lectura",
            "una versión superada", "sustituir un fichero que ya existe", "ni el fichero ni su temporal"))
        for title in dexport.CSV_COLUMNS:
            with self.subTest(column=title):
                self.assertIn(title, self.guide)
        self.assertEqual(dexport.ROAD_EXPORTS, ("surface", "gradient", "reach"))

    def test_the_accessibility_and_its_reading_by_the_verification_are_told(self) -> None:
        """RF-017-24, RF-017-25, RF-012-21, RF-012-22, RF-012-24 (DIFF-017; T35b): §10 dice qué es transitable, lo que da la accesibilidad (cotas, bermas,
        plataformas y zonas «requiere acceso»), sus tres umbrales HIPÓTESIS sin valor por defecto y que no es una entidad con cadena; y §11, las tres
        respuestas de la verificación de la 012 («Cumple», «No cumple» y «Sin comprobar»), que una accesibilidad obsoleta o hecha sobre otra
        superficie no se usa (y la ventana dice por qué) y que cambiarla deja obsoleta la verificación."""
        self.assert_told("## 10. Accesibilidad de las pistas…", (
            "pendiente máxima transitable", "ancho mínimo transitable", "área mínima de un tramo de berma", "ninguno tiene valor por defecto",
            "**no es una entidad con cadena**", "las que no se comunican salen primero", "la superficie final", "unión", "**a 10 filas** en el diálogo",
            "**a 30** en la barra N", "**Ir a**", "no tiene vista previa", "todas las rejillas de cotas de berma", "vuelve a calcular",
            "2·⌊ancho / (2 · lado de la celda)⌋ + 1", "todo umbral menor de 4 m se evalúa como una celda", "la última de la cadena",
            "sobre la final misma no se repite"))
        panels = (EXTENSION_DIR / "bl" / "ui" / "des_panels.py").read_text(encoding="utf-8")  # el texto, sin importar ``bpy``
        self.assertEqual(re.findall(r"^ACCESS_ROWS = (\d+)$", panels, re.MULTILINE), ["10"], "el diálogo corta cada lista a 10 filas")
        self.assertEqual(re.findall(r"^LIST_LIMIT = (\d+)$", panels, re.MULTILINE), ["30"], "la barra N corta cada lista a 30 filas")
        morphology = import_geoblender("design.morphology")
        for width_m, cell_m, cells in ((4.0, 1.0, 5), (3.0, 1.0, 3), (3.9, 2.0, 1), (4.0, 2.0, 3)):  # 2·⌊ancho / (2 · celda)⌋ + 1: lo que la guía dice y reproduce la apertura
            with self.subTest(width=width_m, cell=cell_m):
                self.assertEqual(2 * morphology._disk(width_m / 2.0, cell_m).reach + 1, cells)
        self.assert_told("## 11. La verificación de los límites con la accesibilidad", (
            "**Cumple**", "**No cumple**", "**Sin comprobar**", "alguna accesibilidad al día hecha sobre esa final", "obsoleta", "otra superficie",
            "la ventana de la verificación dice por qué", "deja obsoleta la verificación", "alguna la comunica", "no tiene celdas que incumplan",
            "hace que la final no cumpla"))
        res_messages = (EXTENSION_DIR / "reserves" / "messages.py").read_text(encoding="utf-8")  # el texto, sin importar el módulo
        for code in ("res.verify_access_used", "res.verify_access_stale", "res.verify_access_other_surface"):
            with self.subTest(code=code):
                self.assertIn(f'"{code}"', res_messages)
        for text in ("Complies", "Does not comply", "Not checked"):
            with self.subTest(text=text):
                self.assertIn(text, i18n.load_messages())

    def test_what_the_tasks_left_for_the_guide_is_told(self) -> None:
        """RF-015-18, RF-015-08, RF-015-16, RF-017-03, RF-017-28 (decisiones de la sesión principal tras la T22b, la T27, la T31b, la T33c y la H2; T35b):
        §13 dice lo que las tareas dejaron anotado para la guía: el perfil de la pista y el campo de los nombres de su capa no viajan al traerla (se
        calcula con el campo por defecto, y «Calcular…» **avisa** de ello con la capa, el campo y los puntos que halló, solo si la capa tiene más de un campo de texto: D-2, T44), el
        ramal se calcula después de su pista, la accesibilidad se vuelve a calcular en otra versión, la capa propuesta usada como eje deja obsoleta la pista también si se edita un
        campo, la accesibilidad no tiene «Descartar…», una pista hecha antes de un relleno queda obsoleta y «Recalcular lo obsoleto» **sí** la pone al día (H2-2 desmentido, T44), el
        origen cambiado a un punto quita el apoyo (A-3, T40) y un ciclo se rechaza (A-2); y qué hacen «Calcular…» (plataformas **y pistas**: S-10), «Insertar…» (una plataforma sí, una
        pista no: S-11), «Cambiar parámetro…» (**no es un elemento del menú Proyecto**: S-5) y «Descartar…» con la pista."""
        text = self.guide_section("## 13. Cambiar, recalcular, traer y descartar")
        self.assert_told("## 13. Cambiar, recalcular, traer y descartar", (
            "el perfil de la pista no viaja con ella", "declararlos para el proyecto o en la versión nueva", "el campo de los nombres de la capa tampoco viaja",
            "se calcula con el campo por defecto", "«Calcular…» lo avisa", "con más de un campo de texto", "los puntos que halló", "con un solo campo de texto no avisa",
            "el ramal se calcula después de su pista", "para llevar la accesibilidad a otra versión se vuelve a calcular",
            "no se trae", "la capa propuesta usada como eje deja obsoleta la pista también si se edita un campo", "La accesibilidad no tiene «Descartar…»",
            "una pista hecha antes de un relleno", "lee ese relleno como otro diseño", "«Recalcular lo obsoleto» la pone al día",
            "rehágala sobre la superficie de ese diseño o descártela", "tres pasadas", "sin repetir sin fin",
            "«Calcular…» ofrece las plataformas y las pistas", "se puede insertar una plataforma antes o después de una pista", "no se puede insertar una pista",
            "renombrar una pista no la deja obsoleta", "una cota que da la persona", "«Apoyo retirado»", "«Lo que se apoya en ella»",
            "la capa de ejes queda marcada", "no es un elemento de menú", "Proyecto ▸ Control ▸ Parámetros del proyecto…", "un ciclo",
            "deja de apoyarse en la pista"))
        for stale in ("no la asienta", "«Insertar antes o después de…» abre «Plataforma…» y no se inserta una pista", "se rechazan por nombre", "(menú **Proyecto**)"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)

    def test_the_known_limits_are_told(self) -> None:
        """«Lo que no hace todavía» (T35b, T46; `des.md` §1.9, T34, las decisiones de la sesión principal y el cierre del 22/11/2026) dice los límites de **hoy** y **sin jerga**: lo
        que no se vio en pantalla (se vio con eventos simulados y sin ratón real; no la verificación de los límites con una accesibilidad, la capa propuesta en QGIS, las listas de
        bermas, el objeto de la accesibilidad en la barra N ni el texto de progreso de Esc), los datos originales del proyecto de referencia, la rasante de mínimo movimiento (RF-017-19)
        y las curvas verticales, las rampas vectoriales y el comprobador de pistas, lo medido (la ruta de 62,9 s, grabar con 2,42 M celdas en 16,75 s, que cumple los 15 s por cada 2 M
        celdas que Samuel aceptó al cerrar, lo que ocupa en disco), el estilo de las versiones de la 016 (E-4) y que una pista hecha antes de un relleno no lo tiene en cuenta hasta que se
        rehace (H2-2); **ya no** dice que la vista previa de la propuesta no dibuje el eje (D-1, T44), que «Recalcular lo obsoleto» no asiente la pista ni que la cifra de RNF-017-04 sea de
        Samuel «por decidir». Lo que es de quien mantiene el código (la cifra de RNF-017-04, lo que cuesta el ``check.py``) va al anexo."""
        limits = self.guide_section("## 14. Lo que no hace todavía")
        for fact in ("Samuel los aceptó al cerrar la spec el 22/11/2026", "Lo que no se vio en pantalla", "con eventos simulados y sin ratón real",
                     "la verificación de los límites con una accesibilidad", "la edición de la capa propuesta en QGIS", "el objeto de la accesibilidad en la barra N",
                     "el texto de progreso de Esc", "queda sin medir", "Sin contrastar con los datos originales", "sin ejecutar con los datos originales", "608 m", "136,5 m",
                     "no se fue a la carpeta de expedientes", "programación lineal", "curvas verticales", "sin proceso aparte", "R-35", "R-44", "R-31", "62,9 s", "16,75 s",
                     "15 s por cada 2 millones de celdas de la ventana", "con el que **sí cumple**", "16,61 MiB", "0,316 GiB", "la accesibilidad no se trae",
                     "no tiene «Descartar…»", "la capa de ejes no queda al día sola", "«NO AL DÍA»", "un objeto cargado antes", "la semianchura de 5,75 m", "18 reglas",
                     "«Otra entidad»", "no tiene en cuenta ese relleno hasta que se rehace"):
            with self.subTest(fact=fact):
                self.assertIn(fact, limits)
        for stale in ("(el H3 está pendiente)", "Visto en pantalla", "No se ha visto en pantalla", "no existe ninguna orden que la calcule", "no dibuja el eje", "no se asienta",
                      "RNF-017", "check.py", "worker", "la vista previa de «Proponer el trazado…»", "no cumple los 15 s", "lo decide Samuel", "decisión de Samuel",
                      "Samuel puede cambiarlo", "queda para su revisión"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, limits)
        annex = self.guide_section(ANNEX_HEADING)
        for fact in ("RNF-017-04", "RNF-017-09", "+2,4 s", "`check.py`", "paso `hito`", "desde la 0.4 de la spec (22/11/2026, decisión de Samuel)",
                     "≤ 15 s por cada 2 millones de celdas de la ventana", "`EngraveTest.test_b`", "≈ 18,1 s"):
            with self.subTest(annex=fact):
                self.assertIn(fact, annex)
        self.assertNotIn("la cifra es decisión de Samuel", annex)

    def test_the_style_of_the_entity_layer_the_menu_and_the_start_are_told(self) -> None:
        """RF-015-27, RF-017-05, RF-017-23, RF-017-29, RF-017-27 (T43, T46; E-4, S-19, D-7, D-8, S-5, S-11, S-12, C-2): el cuerpo dice qué hacer con el estilo de 18 reglas de las versiones
        de la 016 (el de hoy tiene 24 reglas: se cuentan en el código), que sin versión activa las órdenes **no** salen en gris y piden una (RF-009-05), que el desnivel es la cota de fin
        menos la de inicio (positivo si la pista sube), que con un relleno posterior que no parte de la explotación hay que elegir la partida, y ya no habla de «estas siete» ni de «las siete»."""
        styles = import_geoblender("core.constraints.styles")
        rules, _symbols = styles._entity_rules()
        self.assertEqual(rules.count("<rule "), 24)
        self.assertEqual(rules.count("<rule ") // 3 - 1, len(styles.ENTITY_KINDS), "el estilo de hoy: cada tipo y «otra entidad», con tres reglas cada uno")
        self.assertEqual(len(styles.ENTITY_KINDS) - 2, 5, "las versiones de la 016 tenían cinco tipos con estilo: 6 × 3 = 18 reglas")
        self.assert_told("## 12. Lo que se ve, lo que se exporta y lo que llega a QGIS", (
            "de 18 reglas", "las pistas salen como «Otra entidad»", "24 reglas", "solo escribe el estilo de una capa que no tiene ninguno por defecto",
            "`layer_styles`", "`des_enl_<vNN>`", "leído en el código y no probado en QGIS", "cota de fin menos cota de inicio", "positivo si la pista sube"))
        self.assert_told("## 3. Antes de empezar", ("**Sin versión activa no salen en gris**", "Esta orden es de una versión: elija la versión activa o cree una"))
        self.assert_told("## 5. Pista…: los tres modos", (
            "otro diseño que no parte de la explotación", "elija usted la superficie que deja el relleno", "`RDW-001@100,5`", "w²/(8R)", "1 cm con w = 1 m y R = 12 m",
            "sobre la línea que une las estaciones"))
        self.assert_told("## 4. Perfil de pista…", ("rechaza lo mismo que esta ventana", "un radio mínimo por debajo de la semianchura de la sección",
                                                   "un ángulo fuera de (0°; 90°)"))
        for heading in ("## 12. Lo que se ve, lo que se exporta y lo que llega a QGIS", "## 15. Dónde queda cada cosa en el proyecto"):
            with self.subTest(heading=heading):
                text = self.guide_section(heading)
                self.assertNotIn("de estas siete", text)
                self.assertNotIn("de las siete", text)
                self.assertIn("la única que se edita en QGIS", text)
        self.assertNotIn("(menú **Proyecto**)", one_line(self.guide))
        self.assertNotIn("| Menú **Proyecto** |", self.guide)


@docs.requires_docs
class RoadsStateDocTest(unittest.TestCase):
    """El índice de specs, el roadmap, el glosario, ``limites-y-restricciones.md``, ``jobs.md``, ``docs/trampas.md`` y el ``CHANGELOG.md`` del código
    dicen el estado de la 017 tras su cierre (Samuel, «Sí, por defecto», 22/11/2026; spec 0.4): **cerrada, en ``main`` y a falta de publicar**, con las tareas
    T01 a T52 hechas (:data:`STATE_017`) y R-36 como dependencia (hecha en sus dos specs, las dos cerradas y publicadas); ninguno la dice ya abierta, sin
    publicar y con la T47 y el H3 por hacer (:data:`STALE_OPEN_017`)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.specs = docs.read(SPECS_INDEX_RELPATH)
        cls.roadmap = docs.read(ROADMAP_RELPATH)
        cls.changelog = one_line(CHANGELOG_PATH.read_text(encoding="utf-8"))
        cls.glossary = docs.read(GLOSSARY_RELPATH)
        cls.index_row = re.search(r"^\| 017 \|.*$", cls.specs, re.MULTILINE)
        cls.roadmap_row = re.search(r"^\| R-40 \|.*$", cls.roadmap, re.MULTILINE)
        cls.ledger = re.findall(r"^\| 2026-11-21 \| R-40.*$", cls.roadmap, re.MULTILINE)
        cls.ledger_convergence = re.findall(r"^\| 2026-11-22 \| R-40: la spec 017 sigue.*$", cls.roadmap, re.MULTILINE)
        cls.ledger_close = re.findall(r"^\| 2026-11-22 \| R-40: Samuel cierra la spec 017.*$", cls.roadmap, re.MULTILINE)

    def test_the_index_says_where_the_017_is(self) -> None:
        """Definición de hecho §3.7 (T35b, T46b y el cierre del 22/11/2026): la fila de la 017 dice que está **Cerrada** (22/11/2026, por Samuel: «Sí, por
        defecto»; spec 0.4), en ``main`` y a falta de publicar, con las tareas T01 a T52 hechas (:data:`STATE_017`), lo que Samuel aceptó (las 19 decisiones, lo
        que no se recorrió en pantalla y el ensayo de CE-017-11 de la sesión principal), lo que sigue sin bloquear (``EngraveTest.test_b`` y el aviso
        ``des.road_carriageway_height``), su guía (``docs/usuario/pistas-y-rampas.md``), R-36 como dependencia, la 012 en su 0.6 y las 51 tareas más las 15 de la
        convergencia; y ya no dice «T01 a T35b», que falte ``tasks.md``, que esté sin publicar ni sin cerrar, ni que las 19 decisiones sigan abiertas."""
        self.assertIsNotNone(self.index_row)
        assert self.index_row is not None
        row = one_line(self.index_row.group(0))
        for fact in (*CLOSED_017_INDEX, STATE_017, "docs/usuario/pistas-y-rampas.md", "CE-017-11", "R-36 (hecha en sus dos specs, las dos cerradas y publicadas)",
                     "51 (T01–T38", "más 15 de convergencia (T39 a T52 y la T46b", "Samuel la cerró aceptando las 19 decisiones de «Decisiones de Samuel» de `tasks.md`",
                     "≤ 15 s por cada 2 M celdas de la ventana", "la spec 0.4 escribe las 20 candidatas", "lo que no se recorrió en pantalla",
                     "el ensayo de CE-017-11 de la sesión principal", "la cifra de menos de 20 minutos con las manos de una persona queda sin medir", "`EngraveTest.test_b`",
                     "`des.road_carriageway_height`", "H3-1 a H3-7 se corrigieron en la T50 a la T52", "**Aprobada** en su 0.3", "la verificación de lo cambiado (T47 a T49"):
            with self.subTest(fact=fact):
                self.assertIn(fact, row)
        for stale in ("falta `tasks.md`", "36 tareas orientativas más", "| — |", "más 10 de convergencia (T39 a T47", "**implementada en `main`, sin publicar**",
                      "(no está cerrada)", "las 19 decisiones de Samuel que no son del código siguen abiertas", *STALE_STATE_017, *STALE_OPEN_017):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, row)

    def test_the_roadmap_says_where_the_017_is(self) -> None:
        """Definición de hecho §3.7 (T35b, T46b y el cierre del 22/11/2026): la fila de R-40 dice que la 017 está **cerrada** por Samuel el 22/11/2026 («Sí, por
        defecto»; spec 0.4), en ``main`` y a falta de publicar (:data:`CLOSED_017`), con las tareas T01 a T52 hechas (:data:`STATE_017`), con R-36 como dependencia
        (hecha en sus dos specs, las dos cerradas y publicadas; D-3) y su guía; su registro del 21/11/2026 lo que pasó entonces (implementada, sin publicar) y los
        dos del 22/11/2026, la convergencia (:meth:`test_the_ledger_tells_the_convergence`) y el cierre; ya no dice «en especificación», que falte ``tasks.md``,
        «de la T01 a la T35b» ni que no esté cerrada."""
        self.assertIsNotNone(self.roadmap_row)
        assert self.roadmap_row is not None
        row = one_line(self.roadmap_row.group(0))
        for fact in (CLOSED_017, STATE_017, "R-36 (hecha en sus dos specs, las dos cerradas y publicadas) como dependencia (D-3)", "R-33, R-36",
                     "docs/usuario/pistas-y-rampas.md", "RF-017-19", "no tiene tarea", "Samuel la cerró aceptando las 19 decisiones de «Decisiones de Samuel» de `tasks.md`",
                     "el ensayo de CE-017-11 de la sesión principal", "la cifra de menos de 20 minutos con las manos de una persona queda sin medir"):
            with self.subTest(fact=fact):
                self.assertIn(fact, row)
        for stale in ("en especificación", "falta `tasks.md`", "36 tareas orientativas)", "de la T01 a la T35b", "a falta del banco de Silvestre (T36)", "**implementada** en `main`",
                      "R-36 (cerrada y publicada)", *STALE_STATE_017, *STALE_OPEN_017):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, row)
        self.assertEqual(len(self.ledger), 1, self.ledger)
        entry = one_line(self.ledger[0])
        for fact in ("la spec 017 queda **implementada en `main`, sin publicar**", "T01 a T35b", "la guía de uso", "el glosario", "el `CHANGELOG.md`",
                     "las tres respuestas de «requiere acceso»", "no marca R-40 como cerrada", "R-36"):
            with self.subTest(ledger=fact):
                self.assertIn(fact, entry)
        self.assertEqual(len(self.ledger_close), 1, self.ledger_close)
        close = one_line(self.ledger_close[0])
        facts = ("Samuel cierra la spec 017 («Sí, por defecto»", "«¿Aceptas por defecto las 19 decisiones y CE-017-11, y que cierre y publique la 017?»", "la verificación de lo cambiado (T47 a T49",
                 "el H3 en pantalla (T38, 22/11/2026", "con eventos simulados y sin ratón real", "H3-1 a H3-7 se corrigieron en la T50 a la T52", "las **19 decisiones**", "la spec **0.4**",
                 "el ensayo de CE-017-11 de la sesión principal", "lo que no se recorrió en pantalla", "**cerrada, a falta de publicar**", "R-36 sigue como dependencia",
                 "`EngraveTest.test_b`", "`des.road_carriageway_height`", "Las dependencias y la frontera de R-40 no cambian")
        self.assertEqual([fact for fact in facts if fact not in close], [])
        self.assertEqual([stale for stale in ("sin publicar", "no marca R-40 como cerrada") if stale in close], [])

    def test_the_five_places_say_the_same_state(self) -> None:
        """Definición de hecho §3.7 (T46b; S-8; el cierre del 22/11/2026): la cabecera y la fila de «Specs» de ``des.md``, el índice de specs, el roadmap y ``AGENTS.md``
        dicen **el mismo estado** de la 017 (:data:`STATE_017`: T01 a T52 hechas, T36 con CE-017-10 sin ejecutar con los datos originales, T47 a T49 y el H3 con su
        corrección) y **el mismo cierre** (:data:`CLOSED_017`; el índice, :data:`CLOSED_017_INDEX`): cerrada por Samuel, en ``main`` y a falta de publicar; que la 017 es
        de las cerradas de ``AGENTS.md``; y ninguno lo dice como antes (T01 a T35b o a T46b, el banco por hacer, la T47 y el H3 por hacer, sin publicar y sin cerrar)."""
        des = docs.read(DES_RELPATH)
        agents = one_line(docs.read("AGENTS.md"))
        assert self.index_row is not None and self.roadmap_row is not None
        start = des.index("\n| 017-des-pistas-y-rampas ") + 1
        places = {"des.md (cabecera)": one_line(des[:des.index("## Responsabilidad")]), "des.md (Specs)": one_line(des[start:des.index("\n", start)]),
                  "specs/README.md": one_line(self.index_row.group(0)), "roadmap.md": one_line(self.roadmap_row.group(0)), "AGENTS.md": agents}
        problems = []
        for where, text in places.items():
            if STATE_017 not in text:
                problems.append(f"{where}: no dice el estado")
            problems += [f"{where}: no dice «{fact}»" for fact in (CLOSED_017_INDEX if where == "specs/README.md" else (CLOSED_017,)) if fact not in text]
            problems += [f"{where}: dice «{stale}»" for stale in (*STALE_STATE_017, *STALE_OPEN_017) if stale in text]
        self.assertEqual(problems, [])
        self.assertIn("001, 013, 014, 015, 016 y 017 cerradas (la 016, acopios, contrafuerte y cuerpos apoyados, cerrada y publicada el 20/11/2026; la 017, pistas y rampas, R-40, ", agents)
        self.assertIn("002, 003, 004, 005, 006, 008, 009, 010, 011 y 012 en `main` y publicadas; 007 sin su T34.", agents)  # lo demás del estado no cambia
        self.assertNotIn("**017** (pistas y rampas, R-40) en `main`", agents)  # ya no es la excepción que iba aparte, sin publicar y sin cerrar

    def test_the_readme_the_bar_and_the_reserves_card_say_the_017_is_closed(self) -> None:
        """Definición de hecho §3.7 (el cierre del 22/11/2026): el ``README.md`` de la carpeta del proyecto, el párrafo de la 017 de la barra superior (§8.7) y la ficha
        de ``res.md`` dicen que la 017 está **cerrada** el 22/11/2026 y a falta de publicar; ninguno dice «sin publicar» de la 017, y la barra dice que E1 a E5 se vieron
        en pantalla en el H3 del 22/11/2026, con eventos simulados y sin ratón real."""
        readme = one_line(re.sub(r"(?m)^> ?", "", docs.read("README.md")))  # sin las marcas «> » de su recuadro
        self.assertIn("(spec 017, en `main`; cerrada el 22/11/2026, a falta de publicar)", readme)
        self.assertNotIn("(spec 017, en `main`, sin publicar)", readme)
        res = one_line(docs.read("docs/arquitectura/modulos/res.md"))
        self.assertIn("**desde la spec 017** (pistas y rampas; en `main`, **cerrada** el 22/11/2026 y a falta de publicar)", res)
        self.assertNotIn("**desde la spec 017** (pistas y rampas; en `main`, sin publicar)", res)
        bar = one_line(docs.read(BS_RELPATH))
        paragraph = bar[bar.index("**Desde la spec 017**"):][:400]
        self.assertEqual(missing(paragraph, ("en `main`, a falta de publicar; **cerrada** el 22/11/2026", "E1 a E5 vistos en pantalla en el H3 del 22/11/2026, con eventos simulados y sin ratón real")), [])
        self.assertNotIn("en `main`, sin publicar", paragraph)

    def test_the_ledger_tells_the_convergence(self) -> None:
        """Definición de hecho §3.7 (T46b y el cierre del 22/11/2026): el primer registro del roadmap del 22/11/2026 cuenta la convergencia de la verificación única (las
        pruebas de plazo, los 16 arreglos de código, las pruebas que faltaban y la documentación), que H2-2 se desmintió con la orden real, que quedaban la T47, el H3 y
        las 19 decisiones de Samuel, y que no marcaba R-40 como cerrada: **se queda como estaba**, es lo que pasó esa mañana; el del 21/11/2026 también; y hay **dos**
        registros del 22/11/2026 de R-40 (el segundo es el del cierre, que prueba :meth:`test_the_roadmap_says_where_the_017_is`)."""
        self.assertEqual(len(re.findall(r"^\| 2026-11-22 \| R-40.*$", self.roadmap, re.MULTILINE)), 2)
        self.assertEqual(len(self.ledger_convergence), 1, self.ledger_convergence)
        entry = one_line(self.ledger_convergence[0])
        facts = ("sigue **implementada en `main`, sin publicar** y sin cerrar", "66 hallazgos", "las pruebas de plazo (T39)", "los 16 arreglos de código (T40 a T44",
                 "las pruebas que faltaban (T45)", "la documentación (T46 y T46b", "H2-2", "se desmintió con la orden real", "la T47", "el H3 en pantalla (T38) con CE-017-11",
                 "**19 decisiones de Samuel**", "no marca R-40 como cerrada")
        self.assertEqual([fact for fact in facts if fact not in entry], [])
        self.assertEqual(len(self.ledger), 1, self.ledger)
        self.assertIn("T01 a T35b", self.ledger[0])  # el registro de lo que pasó el 21/11/2026 no se reescribe

    def test_the_roadmap_puts_the_linear_programming_and_the_vertical_curves_outside(self) -> None:
        """RF-017-19 (S-17; DS-17; T46b): la entrada R-40 ya no da «rasante acotada o por programación lineal» como si estuviera dentro: dice que la rasante es la
        acotada, que la de mínimo movimiento (RF-017-19) es P3 y no tiene tarea, y que las curvas verticales van a R-44 o R-31 «si hacen falta» (la propuesta por
        defecto, que Samuel aceptó el 22/11/2026)."""
        start = self.roadmap.index("**R-40 · Pistas y rampas.**")
        entry = one_line(self.roadmap[start:self.roadmap.index("**R-41 ·", start)])
        facts = ("- rasante acotada;", "RF-017-19", "P3", "no tiene tarea", "curvas verticales", "R-44", "R-31", "«si hacen falta»", "DS-17", "propuesta por defecto, aceptada por Samuel el 22/11/2026: «Sí, por defecto»")
        self.assertEqual([fact for fact in facts if fact not in entry], [])
        self.assertNotIn("rasante acotada o por programación lineal", entry)
        self.assertNotIn("pendiente de Samuel", entry)

    def test_the_changelog_says_what_the_017_does_and_what_it_changes(self) -> None:
        """Definición de hecho §3.7 (T35b y el cierre del 22/11/2026): el ``CHANGELOG.md`` del código, para el ingeniero de minas y sin jerga, dice que la 017 está
        **cerrada** el 22/11/2026, verificada y vista en pantalla con eventos simulados y sin ratón real, a falta de contrastarla con el proyecto de referencia (en su
        entrada y en el resumen del principio), lo nuevo de la 017 (las cinco órdenes, los tres modos, la ruta, el eje con curvas, la rasante, la sección grabada, la
        accesibilidad), las cifras ADOPTADO y HIPÓTESIS con su aviso, lo que cambia la verificación de la 012, las tres órdenes provisionales que desaparecen, lo que
        **no** hace todavía (lo que no se vio en pantalla incluido) y, en «Corregido», el error de la vista que la 017 encontró (la 010: un objeto cuya cota cambia
        sin cambiar su huella)."""
        start = self.changelog.index("- **Pistas y rampas** (spec 017")
        entry = self.changelog[start:self.changelog.index("- **Acopios, contrafuerte y cuerpos apoyados** (spec 016")]
        for fact in ("R-40; cerrada el 22/11/2026: verificada y vista en pantalla con eventos simulados, sin ratón real, a falta de contrastarla con el proyecto de referencia",
                     "**Pista…**", "**Proponer el trazado…**", "**Accesibilidad de las pistas…**",
                     "**Perfil de pista…**", "**Exportar pista…**", "**tres modos**", "una holgura y no un ancho", "**16 rumbos**", "**Los ocho parámetros "
                     "de la ruta son HIPÓTESIS**", "5.000.000 de estados", "**Los tres umbrales de la accesibilidad son HIPÓTESIS**",
                     "ADOPTADO «sin confirmar»", "**Ninguna cifra de la propiedad se da por defecto**", "no se crea sin su confirmación expresa",
                     "«cumple», «no cumple» o «sin comprobar»", "desaparecen", "la pista graba al crearse", "**Lo que no hace todavía**",
                     "La rasante de «mínimo movimiento»", "**se vio en pantalla** (22/11/2026, con eventos simulados y sin ratón real)", "el perfil de la pista no viaja con ella",
                     "la accesibilidad no se trae",
                     # el cierre del 22/11/2026: lo que no se vio en pantalla, lo que Samuel dejó sin ejecutar y la cifra de RNF-017-04 que aceptó
                     "la verificación de los límites con una accesibilidad", "la edición de la propuesta del trazado en QGIS", "el texto de progreso de Esc",
                     "el ensayo de los 20 minutos con las manos de una persona queda sin medir", "quedan sin ejecutar con ellos",
                     "cumple el límite de la spec de 15 s por cada 2 millones de celdas de la ventana",
                     # T46 (S-13, S-16 y lo que cambió la convergencia): el menú, lo que se rechaza y lo que ya se dice distinto
                     "salen en gris con su motivo si el proyecto es de solo lectura o la versión activa está superada", "sin versión activa piden una",
                     "«Calcular…» ofrece también las pistas", "el corte y el relleno de la sección y del borde, y el neto, en líneas distintas",
                     "la desviación máxima del eje", "una pista no puede apoyarse en una que ya se apoya en ella", "el campo de los nombres de su capa",
                     "«Calcular…» lo avisa", "«Recalcular lo obsoleto» la pone al día", "las versiones de la 016 conservan su estilo de 18 reglas"):
            with self.subTest(fact=fact):
                self.assertIn(fact, entry)
        for jargon in ("RF-017", "T3", "T2", "milestone", "`des_rax_", "`des_acc_", "verificación única", "check.py", "RNF-", "CE-0", "H3"):
            with self.subTest(jargon=jargon):
                self.assertNotIn(jargon, entry, "la entrada de la 017 se escribe sin jerga de tareas ni de ficheros")
        for stale in ("no se asienta con", "no dibuja el eje tras calcular", "disponibles con un proyecto en escritura y una versión activa que se puede editar",
                      "hecha en `main`, sin publicar", "sin publicar", "a falta de verla en pantalla", "no se ha visto en pantalla", "probada con Blender sin su interfaz",
                      "no cumple los 15 s", "la cifra la decide Samuel"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, entry)
        summary = self.changelog[self.changelog.index("Y traza pistas y rampas con su perfil"):][:900]  # el resumen del principio
        self.assertIn("(spec 017, cerrada el 22/11/2026 y vista en pantalla con eventos simulados, sin ratón real)", summary)
        self.assertNotIn("sin publicar", summary)
        self.assertNotIn("a falta de verla en pantalla", summary)
        verification = self.changelog[self.changelog.index("- **Verificación por recinto** (spec 012, versión 0.6"):
                                      self.changelog.index("- **La comprobación de cada tarea deja fuera las pruebas pesadas de la spec 017**")]
        for fact in ("las tres respuestas", "«cumple»", "«no cumple»", "«sin comprobar»", "accesibilidad al día", "deja obsoleta la verificación"):
            with self.subTest(verification=fact):
                self.assertIn(fact, verification)
        fixed = self.changelog[self.changelog.index("- En la vista, el objeto de una entidad de diseño"):]
        fixed = fixed[:fixed.index(" - ", 100)] if " - " in fixed[100:] else fixed[:1500]
        for fact in ("«no al día»", "Refrescar", "la plataforma", "la pista", "cota nueva"):
            with self.subTest(fixed=fact):
                self.assertIn(fact, fixed)

    def test_the_glossary_has_the_heading_and_the_gradient(self) -> None:
        """RF-017-02, RF-017-09 (D-8; spec §13; T35b): el glosario gana «Rumbo de avance» (``heading``; el «Rumbo» de antes es el geológico), el perfil de
        pista, el pasillo, el presupuesto de estados y la accesibilidad, y aclara la «Rasante» (el perfil de cotas de una pista: su pendiente es la
        «Pendiente de la rasante»); y §14 resuelve «Rumbo». «grade» sigue siendo solo la ley (§14)."""
        rows = {match.group(1).strip(): match.group(0) for match in re.finditer(r"^\| ([^|]+?) \|.*$", self.glossary, re.MULTILINE)}
        for term, code in (("Rumbo de avance", "`heading`"), ("Perfil de pista", "`road_profile`"), ("Pasillo", "`corridor`"),
                           ("Presupuesto de estados", "`search_budget`"), ("Accesibilidad", "`access`")):
            with self.subTest(term=term):
                self.assertIn(term, rows)
                self.assertIn(code, rows[term])
        for fact in ("azimut", "norte de cuadrícula", "sentido horario", "16", "No es el «Rumbo» geológico"):
            with self.subTest(heading=fact):
                self.assertIn(fact, rows["Rumbo de avance"])
        self.assertIn("Rumbo de avance", rows["Rumbo"])
        for fact in ("perfil de cotas", "`road_gradient`", "Pendiente de la rasante", "No usar `grade`"):
            with self.subTest(gradient=fact):
                self.assertIn(fact, rows["Rasante"])
        for fact in ("holgura", "No es el «Corredor»"):
            with self.subTest(corridor=fact):
                self.assertIn(fact, rows["Pasillo"])
        self.assertIn("| **Rumbo** |", self.glossary)
        self.assertNotIn("Pendiente longitudinal de una pista, en %", rows["Rasante"])

    def test_the_limits_guide_tells_the_three_answers(self) -> None:
        """RF-012-21, RF-012-22, RF-012-24 (DIFF-017; T35b): ``limites-y-restricciones.md`` ya no dice «Sin comprobar (R-40)» ni que lo comprobará la
        entrada de pistas: dice las tres respuestas de «requiere acceso» (cumple, no cumple y sin comprobar) según la accesibilidad al día de la
        versión y remite a la guía de pistas."""
        text = one_line(docs.read(LIMITS_GUIDE_RELPATH))
        for stale in ("Sin comprobar (R-40)", "lo comprobará la entrada de pistas (R-40)"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)
        for fact in ("**Cumple**", "**No cumple**", "**Sin comprobar**", "una «requiere acceso»", "la accesibilidad al día", "pistas-y-rampas.md",
                     "sobre esa final", "tres respuestas"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_jobs_no_longer_lists_a_worker_for_the_3d_route(self) -> None:
        """RF-017-10, RNF-017-02 (S-1; T35): ``jobs.md`` ya no lista ``route_worker`` entre los workers previstos: la ruta 3D de las pistas corre en el
        proceso de Blender, por pasos de 0,05 s y con un presupuesto de estados."""
        text = one_line(docs.read(JOBS_RELPATH))
        self.assertNotIn("`route_worker`", text)
        for fact in ("la ruta 3D de las pistas", "no usa worker", "presupuesto de estados"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_the_traps_have_the_017_lessons(self) -> None:
        """Definición de hecho §3.8 (T35 y T35b): ``docs/trampas.md`` tiene la de la T35 (``gpkg_contents.identifier`` es único entre las tablas de
        un GeoPackage de prueba) además de las de la 017 que ya estaban (la ruta 3D, el pasillo, ``grade``, la pista sin ``protect``…)."""
        text = one_line(docs.read(TRAPS_RELPATH))
        for fact in ("`gpkg_contents.identifier`", "«pasillo de 60 m» es una holgura, no un ancho", "«grade» no se escribe en `design/`",
                     "La pista no tiene `protect`"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)


# --- La 017 (su T46b: las demás fichas, ``tasks.md`` y ``verificacion.md``, tras la convergencia) -------------------------------

VISION_RELPATH = "docs/arquitectura/vision-general.md"
SPEC_017_TASKS_RELPATH = "specs/017-des-pistas-y-rampas/tasks.md"
SPEC_017_VERIFICATION_RELPATH = "specs/017-des-pistas-y-rampas/verificacion.md"
# Los módulos de prueba que renombró la T34b (el nombre antiguo, el nuevo y su carpeta en ``tests/``) y el que el plan llamaba «grade».
RENAMED_TEST_MODULES = (("test_road_ops", "milestone_road_ops", "blender"), ("test_road_extra_ops", "milestone_road_extra_ops", "blender"),
                        ("test_road_calculate_brought", "milestone_road_calculate_brought", "blender"),
                        ("test_road_access_ops", "milestone_road_access_ops", "blender"), ("test_road_steps", "milestone_road_steps_cuts", "blender"),
                        ("test_road_preview_data", "milestone_road_preview_data", "unit/design"), ("test_road_fixtures", "milestone_road_fixtures", "unit/design"),
                        ("test_road_grade", "test_road_gradient", "unit/design"),
                        # Los que movió la T48 (el «verde» de la 017 vuelve a ≤ +3 s): la parte que monta un proyecto de ``test_road_profiles`` y de ``test_road_prepare``
                        # (partidos: lo puro sigue en el «verde») y los módulos enteros de la ruta contra el oráculo y de los casos de referencia de la ruta y de la accesibilidad.
                        ("test_road_profiles", "milestone_road_profiles_operation", "unit/design"),
                        ("test_road_prepare", "milestone_road_prepare_checks", "unit/design"),
                        ("test_road_route_oracle", "milestone_road_route_oracle_cases", "unit/design"),
                        ("test_ref_road_route", "milestone_ref_road_route", "unit/design"),
                        ("test_ref_road_access", "milestone_ref_road_access", "unit/design"))
# Los hallazgos de código que cerró la convergencia (T40 a T44): ``verificacion.md`` §10 los nombra todos.
CLOSED_CODE_FINDINGS = ("A-1", "A-2", "A-3", "A-6", "B-1", "B-2", "B-3", "B-4", "B-5", "B-11", "C-2", "D-1", "D-2", "S-1", "S-2", "S-3")


def missing(text: str, facts: Iterable[str]) -> list[str]:
    """Lo de ``facts`` que ``text`` no dice (una lista vacía, si lo dice todo; más barato que un ``subTest`` por frase y dice todo lo que falta)."""
    return [fact for fact in facts if fact not in text]


@docs.requires_docs
class RoadsCardsDocTest(unittest.TestCase):
    """Las demás fichas de la 017 tras la convergencia (T46b; S-6 a S-9, S-17, S-20, E-5 y H2-2): la guía de las entidades sabe que las pistas existen, la barra
    superior da las etiquetas del catálogo, ninguna ficha dice que «Recalcular lo obsoleto» no asienta una pista anterior a un relleno (H2-2, desmentido), ARQ-13
    lleva los términos de cota, las trampas citan los módulos con su nombre de hoy y recogen lo que aprendió la convergencia, y ``tasks.md`` y ``verificacion.md``
    dicen la cuenta, los nombres antiguos, la nota de M1, qué cerró cada tarea, que Samuel resolvió las 19 decisiones con su propuesta por defecto (22/11/2026) y el
    cierre."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = docs.read(SPEC_017_TASKS_RELPATH)
        cls.verification = docs.read(SPEC_017_VERIFICATION_RELPATH)

    def test_the_entities_guide_knows_the_roads_exist(self) -> None:
        """RF-017-01, RF-015-01 (S-6; T46b): la guía de las entidades de diseño (015) ya no dice que las pistas (R-40) «aún no existen» ni que los acopios, el
        contrafuerte y los cuerpos apoyados «usarán este mismo marco en la spec 016»: dice que las de la 016 y las pistas de la 017 ya lo usan y que solo la balsa, el
        canal y los rellenos con balance faltan."""
        guide = one_line(docs.read(ENTITIES_GUIDE_RELPATH))
        for stale in ("usarán este mismo marco en la spec 016", "las pistas (R-40) son entidades que usarán este marco", "las pistas (R-40) son entidades que usarán"):
            self.assertNotIn(stale, guide)
        self.assertEqual(missing(guide, ("y las pistas y rampas (spec 017) usan este mismo marco", "(spec 016) y las pistas y rampas (spec 017) **ya usan este marco**",
                                         "la balsa y el canal (R-37) y los rellenos con balance (R-39) son entidades que usarán este marco y **aún no existen**")), [])

    def test_the_bar_table_gives_the_labels_of_the_catalog(self) -> None:
        """RF-017-29, RF-015-28 (S-9; BS §8.7; T46b): la tabla de «Pistas y entidades» de la barra superior da, de las cinco órdenes de la 017 que están en el menú, la
        **etiqueta del catálogo** («Pista…», «Proponer el trazado…», «Accesibilidad de las pistas…», «Perfil de pista…» y «Exportar pista…»); ``test_catalog_matches_docs``
        solo compara los identificadores. Y la frase de la disponibilidad ya no dice «desactivadas con su motivo en los demás casos» (D-7: sin versión piden una)."""
        table = section(docs.read(BS_RELPATH), "### 8.7 Diseño")
        commands = catalog.load().commands
        wrong = []
        for name in ("des_create_road", "des_propose_road", "des_road_access", "des_edit_road_profile", "des_export_road"):
            row = re.search(rf"^\| ([^|]+?) \| `{name}` \|", table, re.MULTILINE)
            if row is None or row.group(1) != commands[f"geoblender.{name}"].label_es:
                wrong.append((name, row and row.group(1)))
        self.assertEqual(wrong, [])
        text = one_line(table[table.index("**Desde la spec 017**"):])  # solo el párrafo de la 017: los de la 015 y la 016 son de sus specs
        self.assertNotIn("están disponibles con un proyecto en escritura y una versión activa que se puede editar y desactivadas con su motivo en los demás casos", text)
        self.assertIn("**sin versión activa quedan activas y piden una**", text)

    def test_h2_2_is_denied_in_every_card_that_said_it(self) -> None:
        """RF-017-05 (b), RF-015-15, RF-015-17 (S-18, DS-13; T44 y T46b): ninguna ficha dice ya que «Recalcular lo obsoleto» **no la asienta** si una pista anterior a un
        relleno se le apoya (la orden real converge en tres pasadas: ``milestone_road_ce.BeforeTheFillTest.test_c``): ni ``paneles-contextuales.md``, ni la ficha de
        ``des``, ni ``docs/trampas.md``; dicen en cambio que la pista no tiene en cuenta el relleno hasta que se rehace sobre su superficie."""
        des, panels, traps = docs.read(DES_RELPATH), docs.read(PC_RELPATH), docs.read(TRAPS_RELPATH)  # sin ``one_line`` de ficheros enteros: cada frase va en un renglón
        for where, text in (("des.md", des), ("paneles-contextuales.md", panels), ("trampas.md", traps)):
            self.assertIsNone(re.search(r"no\s+la\s+asienta", text), where)
        self.assertEqual(missing(des, ("**H2-2, desmentido:**", "«Recalcular lo obsoleto» **sí la pone al día**", "converge en tres pasadas")), [])
        self.assertIn("«Recalcular lo obsoleto» la pone al día y, si debe tener en cuenta ese diseño, rehacerla sobre su superficie o descartarla", panels)
        self.assertEqual(missing(traps, ("(**desmentido: no es un bucle**, véase abajo)", "**Corregido el 22/11/2026 (T44 y T46b): la afirmación era falsa.**",
                                         "converge** en 3 pasadas", "**No escribas un límite en la barra N, la guía y las fichas sin una prueba con la orden real**")), [])

    def test_arq_13_lists_the_elevation_terms(self) -> None:
        """ARQ-13, principio 6 (E-5; T45 y T46b): la fila de ARQ-13 de ``vision-general.md`` dice que la lista cerrada de ``ABS_COORD_TOKENS`` incluye ahora ``level``,
        ``cota`` y ``elev``, que son los que la regla tiene de verdad."""
        source = (ROOT / "tools" / "gbtools" / "rules" / "props.py").read_text(encoding="utf-8")
        tokens = source[source.index("ABS_COORD_TOKENS"):source.index("FLOAT_PROPERTIES")]
        elevation = ("level", "cota", "elev")
        self.assertEqual(missing(tokens, [f'"{term}",' for term in elevation]), [])  # lo prueban ``test_geoorigin_properties`` (la regla) y esta (que la ficha lo dice)
        start = docs.read(VISION_RELPATH)
        row = start[start.index("\n| ARQ-13 |"):]
        row = one_line(row[:row.index("\n", 1)])
        self.assertEqual(missing(row, [f"`{term}`" for term in elevation] + ["desde la 017 (T45, hallazgo E-5)", "`dest_level`", "017 (T45: los términos de cota)"]), [])

    def test_the_traps_cite_the_renamed_modules_and_tell_what_the_convergence_learnt(self) -> None:
        """Definición de hecho §3.8 (S-7; T46b): ``docs/trampas.md`` ya no cita ``test_road_fixtures``, ``test_road_ops``, ``test_road_access_ops`` ni ``test_road_steps``
        (T34b: ahora ``milestone_road_fixtures``, ``milestone_road_ops``, ``milestone_road_access_ops`` y ``milestone_road_steps_cuts``) sin decir «antes»; los módulos
        con su nombre nuevo existen; y recoge lo que aprendieron la T39 a la T45 (el recorte de un intervalo, el paso de cota sin tope, la rejilla de la línea que se
        corta, la zona de peso 1, la superficie por defecto de la accesibilidad, la vista previa de una propuesta, la cita de la guía, el hito con proyecto compartido
        y el ``git stash``), sin repetir lo que ya decían ``OperationStart.carry``, ``bank_folder`` y ``one_unit_per_event``."""
        text = docs.read(TRAPS_RELPATH)  # sin ``one_line`` del fichero entero: cada trampa es un renglón
        wrong = []
        for old, new, folder in RENAMED_TEST_MODULES[:5]:
            if not (ROOT / "tests" / folder / f"{new}.py").is_file():
                wrong.append(f"no existe {new}")
            if text.count(old) != text.count(f"antes `{old}"):
                wrong.append(f"{old}: se cita sin «antes»")
        self.assertEqual(wrong, [])
        self.assertEqual(missing(text, ("`milestone_road_steps_cuts.RoadStepsTest.test_a_esc_in_each_phase_of_calculating_leaves_nothing`", "`milestone_road_access_ops.test_e`",
                                        "`milestone_road_fixtures.py`", "`milestone_road_ops.py`", "`tests/blender/milestone_road_access_ops.py`",
                                        "**`np.clip` de los dos extremos de un intervalo que cae entero fuera del rango lo vuelve un valor permitido**",
                                        "un cero de más al teclear `level_step_m`", "**Una búsqueda por rejilla que sustituye a un O(n²) pierde un par si las cajas no llevan margen",
                                        "**«Hay zona» no es «peso > 1»", "`access_store._chain_origin`", "`RoadAsk(propose=True)`", "**Cambiar un texto de la barra N o del catálogo",
                                        "**En un hito con un proyecto compartido, añadir una pista antes", "**Un `git stash` «para comparar»", "`carry=False`", "`bank_folder`",
                                        "step_modals.one_unit_per_event")), [])
        self.assertEqual(text.count("`tests.support.step_modals.one_unit_per_event`"), 1)  # la de la T39 no se duplica

    def test_tasks_say_the_count_the_renamed_modules_and_the_m1_note(self) -> None:
        """Definición de hecho §3.7 (S-7, S-20, D-7; T46b): ``tasks.md`` de la 017 lleva, sin reescribir las líneas viejas, la nota con la cuenta real («Son 38 tareas» eran
        las de la redacción: 61 entradas, de las que quedan la T47 y el H3), la tabla «nombre antiguo → nuevo» de los módulos de prueba que renombró la T34b (y
        ``test_road_grade`` → ``test_road_gradient``), cada uno con su módulo nuevo existente, y la nota a la comprobación manual M1 (sin versión activa, las órdenes
        quedan activas y piden una: RF-009-05, como la 013 y la 015)."""
        start = self.tasks.index("> **Nota de la T46b (22/11/2026) — la cuenta y los nombres.**")
        note = self.tasks[start:self.tasks.index("**Requisitos previos.**", start)]
        text = one_line(note)
        self.assertEqual(missing(text, ("*«Son 38 tareas»* es la cuenta de la redacción", "**61 entradas de tarea**", "las **51** de la T01 a la T38",
                                        "las **10** de la convergencia (T39 a T47 y la T46b", "**2 pendientes: la T47** (la verificación de lo cambiado, de la sesión principal) **y el H3 (T38)**",
                                        "**no se reescriben**")), [])
        rows = {match.group(1): (match.group(2), match.group(3)) for match in re.finditer(r"^> \| `(test_[a-z_]+)`[^|]*\| `(\w+)`[^|]*\| `([^`]+)` \|$", note, re.MULTILINE)}
        self.assertEqual(rows, {old: (new, f"tests/{folder}/") for old, new, folder in RENAMED_TEST_MODULES})
        self.assertEqual([new for _, new, folder in RENAMED_TEST_MODULES if not (ROOT / "tests" / folder / f"{new}.py").is_file()], [])
        m1 = one_line(self.tasks[self.tasks.index("- **M1 (T29b)**"):self.tasks.index("- **M2 (T29)**")])
        self.assertEqual(missing(m1, ("la orden sale desactivada con su motivo", "*Nota de la T46b (D-7; 22/11/2026):* **sin versión activa las órdenes quedan activas y piden una**",
                                      "RF-009-05", "como las de la 013 y la 015", "**no se reescribe**")), [])

    def test_the_decisions_of_samuel_say_what_the_convergence_did_and_what_he_answered(self) -> None:
        """Definición de hecho §3.7 (T46b y el cierre del 22/11/2026): «Decisiones de Samuel» de ``tasks.md`` da la tabla de lo que cerró cada tarea de la convergencia con
        sus commits y, bajo **cada una de las 19** decisiones, lo que la convergencia hizo con ella (en cursiva: DS-13 y DS-15 aplicadas, DS-1, 4, 11, 12, 14 y 17 cambiadas) y,
        **resuelta ya**, la línea «Resolución (22/11/2026, «Sí, por defecto»)» de lo que Samuel aceptó («Sí, por defecto»): ya no dice «pendiente» ni que Samuel no haya dicho nada;
        lo que quedó para la siguiente entrada (``EngraveTest.test_b`` y el aviso ``des.road_carriageway_height``) está dicho; la cabecera dice que la spec es la 0.4, cerrada; y
        ``verificacion.md`` §10 (que no se reescribe) nombra los 16 hallazgos de código cerrados y su §12 el cierre."""
        self.assertIn("**Spec:** `spec.md` (versión 0.4, **cerrada el 22/11/2026**;", self.tasks)
        block = self.tasks[self.tasks.index("## Decisiones de Samuel"):self.tasks.index("## Decisión de la sesión principal")]
        self.assertTrue(block.startswith("## Decisiones de Samuel (22/11/2026: «Sí, por defecto»)"))
        self.assertEqual(missing(one_line(block), ("**Lo que cerró la convergencia (T39 a T46b; 22/11/2026)**", "`6581f8b`", "`e3d4604`", "`7e293a5`", "`0aacd0d`", "`e1e7747`",
                                                   "`c32742d`", "`9755219`", "`180f233`", "**Samuel aceptó el 22/11/2026, en el chat, con «Sí, por defecto»**",
                                                   "**las 19 decisiones de esta sección con la propuesta por defecto de cada una**", "Después se hicieron la **T47**",
                                                   "**Lo que queda para la siguiente entrada, sin bloquear el cierre:**", "`EngraveTest.test_b`",
                                                   "`des.road_carriageway_height`")), [])
        for stale in ("**ninguna está resuelta: Samuel no ha dicho nada**", "Quedan la **T47**", "**Resolución:** pendiente"):
            self.assertNotIn(stale, block)
        items = [item for item in re.split(r"(?m)^(?=\d+\. \*\*)", block[block.index("1. **RNF-017-04"):]) if item.strip()]
        self.assertEqual(len(items), 19)
        wrong = []
        answer = "**Resolución (22/11/2026, «Sí, por defecto»):**"
        for number, item in enumerate(items, start=1):
            after = item.find("*Tras la convergencia")
            if not item.startswith(f"{number}. **") or not 0 < after < item.find(answer) or "**Resolución:**" in item:
                wrong.append(number)
        self.assertEqual(wrong, [], "las decisiones sin su nota «Tras la convergencia» o sin la resolución de Samuel del 22/11/2026")
        thirteen, fifteen = one_line(items[12]), one_line(items[14])
        self.assertIn("el código y los textos ya están como proponía esta decisión; falta solo que Samuel la dé por vista", thirteen)  # la nota de la convergencia, que no se reescribe
        self.assertIn("**Dado por visto**", thirteen)  # y lo que contestó
        self.assertEqual(missing(fifteen, ("la propuesta por defecto está aplicada", "Sigue pendiente solo lo del formato guardado", "**Avisar**")), [])
        one = one_line(items[0])
        self.assertEqual(missing(one, ("«**≤ 15 s por cada 2 M celdas de la ventana**»", "un 25 % de margen", "**Queda por aplicar en el código:** `EngraveTest.test_b`")), [])
        section_10 = one_line(self.verification[self.verification.index("## 10. Tras la convergencia"):])
        self.assertEqual(missing(section_10, ("(T39 a T46b; 22/11/2026)", "**La 017 no está cerrada ni publicada.**", "**(i) 16 arreglos de código**", "**19 decisiones**",
                                              "ninguna tiene resolución", "la **causa de la intermitencia de `test_road_bank.LatestTest`**", "la **T47**", "el **H3 en pantalla**",
                                              "no se marca cerrada") + CLOSED_CODE_FINDINGS), [])  # §10 cuenta cómo estaba el 22/11/2026 por la mañana: no se reescribe
        section_12 = one_line(self.verification[self.verification.index("## 12. Cierre (22/11/2026)"):])
        self.assertEqual(missing(section_12, ("**Samuel cerró la spec 017 el 22/11/2026 en el chat con «Sí, por defecto»**",
                                              "«¿Aceptas por defecto las 19 decisiones y CE-017-11, y que cierre y publique la 017?»", "**Las 19 decisiones**",
                                              "**cada una con su propuesta por defecto**", "**sin ejecutar con los datos originales**", "**el ensayo de la sesión principal**",
                                              "**La cifra de «menos de 20 minutos» con las manos de una persona queda sin medir**", "**Lo que no se recorrió en pantalla**",
                                              "**La spec pasa a su 0.4 y a Cerrada**", "las 20 candidatas de §7", "**Las erratas de §8 siguen sin editarse**",
                                              "`EngraveTest.test_b`", "`des.road_carriageway_height`", "**cerrada, en `main` y a falta de publicar**")), [])


def road_net():
    """``design.road_net`` (perezoso, como :func:`roadprofiles`)."""
    return import_geoblender("design.road_net")


def road_model():
    """``design.road_model`` (perezoso, como :func:`roadprofiles`)."""
    return import_geoblender("design.road_model")


if __name__ == "__main__":
    unittest.main()
