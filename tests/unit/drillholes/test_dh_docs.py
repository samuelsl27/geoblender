# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sondeos frente a su documentación (spec 005, T35; plan 005 §5.6).

Como la topografía (``tests/unit/gis/test_gis_docs.py``) y la procedencia
(``tests/unit/core/provenance/test_format_docs.py``), el código manda y la documentación lo
describe; estas pruebas avisan de que se separan:

- ``docs/arquitectura/modulos/dh.md``: lo que nombra de ``drillholes`` en su API existe en el
  código y la API nombra cada módulo del paquete; nombra cada tipo de operación de
  ``drillholes.provenance``, cada trabajo de ``drillholes.jobs`` y cada parámetro de
  ``drillholes.params``, con los de la regla bajo el límite de detección en su párrafo;
- ``docs/arquitectura/datos/sondeos.md``: el SQL de cada tabla de los sondeos (la base, lo
  calculado y lo importado) y de cada índice está una sola vez en un bloque ``sql``, igual que
  el que escribe ``drillholes.schema.create_table`` salvo los comentarios, los espacios y las
  comillas (lo importado, con el nombre ``dh_src_<rol>_<nombre>_<entrada8>``), con el título de
  cada columna (su alias en QGIS) en su comentario; cada código de la validación tiene su fila
  con su nivel y su alcance, y la regla bajo el límite se nombra por sus dos claves (no la
  ``dh.below_dl_policy`` del plan de antes de la alineación);
- ``docs/arquitectura/datos/formato-proyecto.md`` §3.11: las tablas de la base y de lo
  calculado y el nombre de lo importado de cada papel.

(T59; F-4 y F-5 de la verificación de la 005: la guía, el CHANGELOG y las fichas decían cosas
que el código no hace) Además, lo que se puede comparar por máquina:

- en ``dh.md``, la fila de cada tipo de operación dice si se repite sola, nombra ``pyproj`` si
  la operación la registra y nombra los parámetros que lee;
- en ``sondeos.md``, los niveles de ``dh_validation_issue`` son los de
  ``drillholes.validate.Level``, ``length_m`` de ``dh_trace`` es una profundidad y la traza
  guardada no tiene vértices en los límites de los tramos (``drillholes.jobs.trace_rows``);
- en la guía de uso (``docs/usuario/sondeos.md``): la orden que abre «Importar un fichero…»
  con cada extensión, como ``bl/ops/io.py`` (también lo que dice de ella el CHANGELOG del
  código); las entradas del roadmap de lo que sigue en gris en el menú «Sondeos», del
  catálogo de comandos; los campos obligatorios y opcionales de cada papel de una tabla, los
  de ``interop.drillholes_tabular``; los niveles de la lista de la validación; dónde queda
  cada tabla en el proyecto, y qué deja obsoleta una traza.

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
"""

from __future__ import annotations

import pkgutil
import re
import sqlite3
import unittest
from collections.abc import Iterator
from contextlib import closing
from typing import Any

from tests.support import docs, io_routes
from tests.support.bs_tables import backticked, section, tables
from tests.support.package import import_geoblender
from tests.support.repo import ROOT

drillholes = import_geoblender("drillholes")
schema = import_geoblender("drillholes.schema")
provenance = import_geoblender("drillholes.provenance")
dh_params = import_geoblender("drillholes.params")
dh_jobs = import_geoblender("drillholes.jobs")
dh_report = import_geoblender("drillholes.report")
validate = import_geoblender("drillholes.validate")
tabular = import_geoblender("interop.drillholes_tabular")
gpkg_base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
core_catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")

DH_RELPATH = "docs/arquitectura/modulos/dh.md"
DATA_RELPATH = "docs/arquitectura/datos/sondeos.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
GUIDE_RELPATH = "docs/usuario/sondeos.md"
CHANGELOG = ROOT / "CHANGELOG.md"
DH_NAME = re.compile(r"^drillholes(?:\.[A-Za-z_]\w*)+$")
UID = "3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f"  # el uid de una entrada (un UUID en texto)
SOURCE_SUFFIX = "_<nombre>_<entrada8>"  # lo importado en la documentación: dh_src_<rol>_…
PROJECT_EPSG = 25830

SQL_FENCE = re.compile(r"^```sql\n(.*?)^```", re.MULTILINE | re.DOTALL)
COMMENT = re.compile(r"--[^\n]*")
CREATE = re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\s+([^\s(]+)", re.IGNORECASE)
CREATE_TABLE = re.compile(r"^CREATE\s+TABLE\s+([^\s(]+)\s*\(", re.IGNORECASE)
LEVELS = {"error": "Error", "warning": "Aviso"}
SCOPES = {"hole": "S", "table": "T", "record": "R", None: "—"}

DH_MENU = "GEOBLENDER_MT_ui_drillholes"
DH_COMMAND = "geoblender.dh_"
IMPORT_FILE = "«Importar un fichero…»"
IMPORT_FILE_HEADING = "### 3.7 Desde «Importar un fichero…»"
IMPORT_ROW = "Proyecto ▸ Intercambio ▸ Importar"
"""La fila de la tabla de las órdenes de la guía que dice qué abre «Importar un fichero…»."""
MENTIONED = (
    re.compile(r"`(\.\w+)` en «Importar un fichero…»"),
    re.compile(r"«Importar un fichero…» con un (\w+)(?: o un (\w+))?"),
)
"""Cómo dicen un texto de la guía o del CHANGELOG que «Importar un fichero…» abre con una
extensión el importador de los sondeos: «un `.mdb` en «Importar un fichero…»» o
««Importar un fichero…» con un XLSX» (el formato es la extensión)."""
ROLES_HEADING = "### 3.1 Los ficheros y sus papeles"
EACH_ELEMENT = "una columna por elemento"
"""Lo que, además de sus campos, necesita una tabla de análisis en columnas."""
ROLE_FIELD_LABELS = {("element_catalog", "name"): "nombre"}
"""Los campos que en un papel se llaman de otro modo que en ``FIELD_LABELS`` (el asistente los
nombra así: ``bl.props.dh.ROLE_FIELD_MSGIDS``)."""
ARTICLE = re.compile(r"^(?:el|la|los|las)\s+")
ITEM_SEPARATOR = re.compile(r",\s*|\s+y\s+|\s+e\s+")
VERTICES_AT_INTERVALS = re.compile(r"vértices[^;.]*tramo")
"""Una frase que pone vértices de la traza en los límites de los tramos (solo las curvas de la
vista los tienen)."""
STALE_BY_METHOD = "el método de un sondeo"
"""El método es de la operación, no de un sondeo (O-6 de la verificación): con otro, «Calcular
trazas…» las recalcula todas."""


def resolves(dotted: str) -> bool:
    """``drillholes.<módulo>[.<nombre>…]`` existe en el código."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj = import_geoblender(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for name in parts[cut:]:
            if not hasattr(obj, name):
                return False
            obj = getattr(obj, name)
        return True
    return False


def normalized(sql: str) -> str:
    """El SQL de una sentencia sin comentarios ni comillas dobles y con los espacios reducidos
    (ninguno junto a paréntesis y comas)."""
    text = COMMENT.sub(" ", sql).replace('"', "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([(),])\s*", r"\1", text)
    return text.strip().rstrip(";").strip()


def documented_statements(document: str) -> dict[str, list[str]]:
    """Las sentencias ``CREATE TABLE`` y ``CREATE INDEX`` de los bloques ``sql``, normalizadas,
    por nombre (una lista: un nombre puede salir más de una vez)."""
    found: dict[str, list[str]] = {}
    for block in SQL_FENCE.findall(document):
        for statement in COMMENT.sub(" ", block).split(";"):
            match = CREATE.match(statement)
            if match is not None:
                found.setdefault(match.group(1), []).append(normalized(statement))
    return found


def documented_columns(document: str) -> dict[str, list[tuple[str, str]]]:
    """Las líneas de cada ``CREATE TABLE`` de los bloques ``sql``, por tabla: (lo que no es
    comentario, el comentario)."""
    found: dict[str, list[tuple[str, str]]] = {}
    for block in SQL_FENCE.findall(document):
        current: list[tuple[str, str]] | None = None
        for line in block.splitlines():
            code, _, comment = line.partition("--")
            match = CREATE_TABLE.match(code.strip())
            if match is not None:
                current = found.setdefault(match.group(1), [])
            if current is not None:
                current.append((code.strip(), comment.strip()))
                if code.rstrip().endswith(";"):
                    current = None
    return found


def doc_name(layout: object) -> str:
    """El nombre de la tabla de ``layout`` en la documentación."""
    return f"{layout.name}{SOURCE_SUFFIX}" if layout.source else layout.name


def code_statements() -> dict[str, str]:
    """El SQL de cada tabla de los sondeos y de cada índice, como lo escribe
    ``drillholes.schema.create_table`` en un GeoPackage nuevo, normalizado y por el nombre de
    la documentación."""
    crs = georef.load_catalog().horizontal(PROJECT_EPSG)
    statements: dict[str, str] = {}
    with closing(sqlite3.connect(":memory:")) as conn:
        gpkg_base.create_base(conn, crs)
        names: dict[str, str] = {}
        for layout in schema.LAYOUTS.values():
            table = (schema.source_table(str(layout.role), "nombre", UID) if layout.source
                     else layout.name)
            schema.create_table(conn, layout, table, crs.epsg)
            names[table] = doc_name(layout)
        for name, table, sql in conn.execute(
                "SELECT name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL"):
            if table not in names:
                continue
            text = sql.replace(f'"{table}"', names[table]).replace(table, names[table])
            statements[name.replace(table, names[table])] = normalized(text)
    return statements


def menu_commands(catalog: Any, menu_id: str) -> Iterator[Any]:
    """Las órdenes del menú ``menu_id`` del catálogo de comandos (también las de sus
    submenús y sus accesos cruzados ↗)."""
    for group in catalog.menus[menu_id].groups:
        for item in group.items:
            if item.key is None:
                continue
            command = catalog.commands[item.key]
            if command.kind == "menu" and command.key in catalog.menus:
                yield from menu_commands(catalog, command.key)
            else:
                yield command


def delivered(catalog: Any, command: Any) -> bool:
    """Si la entrada que trae ``command`` ya entrega sus órdenes."""
    entry = catalog.entries.get(command.entry)
    return bool(entry is not None and entry.delivered)


def list_items(text: str) -> tuple[list[str], bool]:
    """Los elementos de una lista escrita («Sondeo, X, Y y Z», «el método y el identificador
    externo…»), sin lo que va entre paréntesis ni los artículos, en minúsculas; y si acaba en
    «…» (una lista que no los dice todos)."""
    text = re.sub(r"\s*\([^)]*\)", "", text).strip().rstrip(".").strip()
    open_ended = text.endswith("…")
    items = [ARTICLE.sub("", item.strip().rstrip("…").strip().lower())
             for item in ITEM_SEPARATOR.split(text.rstrip("…"))]
    return [item for item in items if item], open_ended


def field_label(role: str, field: str) -> str:
    """Cómo se llama el campo ``field`` de una tabla del papel ``role``, como en
    :func:`list_items` («X (este)» es «x»)."""
    label = ROLE_FIELD_LABELS.get((role, field), tabular.FIELD_LABELS[field])
    return re.sub(r"\s*\([^)]*\)", "", label).strip().lower()


def changelog_drillholes() -> str:
    """La entrada de los sondeos (spec 005) de «[Sin publicar]» del CHANGELOG del código."""
    text = CHANGELOG.read_text(encoding="utf-8")
    start = text.index("- **Sondeos** (spec 005)")
    following = re.search(r"^- \*\*", text[start + 2:], flags=re.MULTILINE)
    return text[start:start + 2 + following.start()] if following else text[start:]


def one_line(text: str) -> str:
    """``text`` con cada salto de línea y cada grupo de blancos como un espacio."""
    return " ".join(text.split())


def mentioned_extensions(text: str) -> list[str]:
    """Las extensiones con que ``text`` dice que «Importar un fichero…» abre un importador de
    los sondeos (:data:`MENTIONED`), en minúsculas y con su punto."""
    found: list[str] = []
    for pattern in MENTIONED:
        for match in pattern.finditer(one_line(text)):
            found.extend(f".{name.lstrip('.').lower()}" for name in match.groups() if name)
    return found


@docs.requires_docs
class DhModuleDocTest(unittest.TestCase):
    """``modulos/dh.md`` nombra la API, las operaciones, los trabajos y los parámetros que
    existen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(DH_RELPATH)

    def test_named_api_exists(self) -> None:
        """RF-005-01, RF-005-12, RF-005-16, RF-005-20, RF-005-21 (plan 005 §5.3.2 y §5.6): todo
        lo que la API de la ficha nombra de ``drillholes`` existe, y la nombra cada módulo del
        paquete."""
        api = section(self.text, "## API pública")
        named = {token for token in backticked(api) if DH_NAME.match(token)}
        self.assertGreater(len(named), 40)
        self.assertEqual(sorted(name for name in named if not resolves(name)), [])
        for info in pkgutil.iter_modules(drillholes.__path__):
            with self.subTest(module=info.name):
                self.assertTrue(any(name == f"drillholes.{info.name}"
                                    or name.startswith(f"drillholes.{info.name}.")
                                    for name in named))

    def test_operations_jobs_and_parameters(self) -> None:
        """RF-005-12, RF-005-16, RF-005-20, RF-005-26 (plan 005 §5.6.3, §5.6.4 y §5.6.7): la
        ficha nombra cada tipo de operación, cada trabajo y cada parámetro, con los de la
        regla bajo el límite de detección en su párrafo."""
        operations = section(self.text, "## Operaciones, datos y parámetros")
        named = set(backticked(operations))
        for declared in provenance.OPERATION_TYPES:
            with self.subTest(operation=declared.op_type):
                self.assertIn(declared.op_type, named)
        for worker in dh_jobs.WORKER_NAMES:
            with self.subTest(worker=worker):
                self.assertIn(worker, named)
        for definition in dh_params.DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, named)
        rule = next(paragraph for paragraph in operations.split("\n\n")
                    if paragraph.startswith("**La regla bajo el límite**"))
        self.assertEqual(
            sorted(token for token in backticked(rule) if token in dh_params.PARAMS),
            sorted(dh_params.BELOW_DL_KEYS))

    def test_operation_rows(self) -> None:
        """RF-005-12, RF-005-16, RF-005-20 (plan 005 §5.6.4; T59, F-4 de la verificación: la
        fila de ``dh.import_recmin`` no decía que registra ``pyproj``): en la tabla de los
        tipos de operación, la fila de cada uno dice si se repite solo, nombra ``pyproj`` si y
        solo si la operación la registra como biblioteca que influye en sus resultados
        (``OperationType.libraries``) y nombra cada parámetro que lee (o su prefijo, con
        «.*»)."""
        operations = section(self.text, "## Operaciones, datos y parámetros")
        rows = {row[0].strip("`"): row for table in tables(operations) for row in table
                if row and row[0].startswith("`dh.")}
        self.assertEqual(sorted(rows), sorted(t.op_type for t in provenance.OPERATION_TYPES))
        for declared in provenance.OPERATION_TYPES:
            row = rows[declared.op_type]
            named = set(backticked(" ".join(row)))
            with self.subTest(operation=declared.op_type):
                self.assertEqual(row[1].startswith("Sí"), declared.repeatable)
                self.assertEqual(provenance.PYPROJ in named,
                                 provenance.PYPROJ in declared.libraries)
                for key in declared.params:
                    self.assertTrue(key in named or any(
                        token.endswith(".*") and key.startswith(token[:-1])
                        for token in named), key)


@docs.requires_docs
class DrillholeDataDocTest(unittest.TestCase):
    """``datos/sondeos.md`` describe las tablas que escribe el código y sus validaciones."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(DATA_RELPATH)

    def test_tables_as_in_the_code(self) -> None:
        """RF-005-01, RF-005-02, RF-005-11 (plan 005 §5.6.1, D17 y D-20): cada tabla de los
        sondeos y cada índice está una sola vez en el documento, con el SQL del código; sin
        ``stale`` ni ``operation_uid`` en las trazas ni en las incidencias (los da la 008)."""
        documented = documented_statements(self.text)
        statements = code_statements()
        self.assertEqual(len([name for name in statements if not name.startswith("idx_")]),
                         len(schema.LAYOUTS))
        for name, sql in statements.items():
            with self.subTest(name=name):
                self.assertEqual(documented.get(name, []), [sql])
        for name in ("dh_trace", "dh_validation_issue"):
            for sql in documented.get(name, []):
                with self.subTest(table=name):
                    self.assertNotRegex(sql, r"\b(?:stale|operation_uid)\b")

    def test_each_column_with_its_title(self) -> None:
        """RF-005-01 (plan 005 §5.2.1): la línea de cada columna lleva en su comentario el título
        en español que QGIS muestra como su alias, entre comillas angulares."""
        documented = documented_columns(self.text)
        for layout in schema.LAYOUTS.values():
            lines = documented.get(doc_name(layout), [])
            for column, title in layout.titles.items():
                with self.subTest(table=layout.name, column=column):
                    found = [comment for code, comment in lines
                             if re.match(rf"{column}\s+[A-Z]", code)]
                    self.assertEqual(len(found), 1)
                    self.assertIn(f"«{title}»", found[0])

    def test_validation_codes_rule_and_below_detection_limit(self) -> None:
        """RF-005-16, RF-005-17, RF-005-26 (spec 005 §4.4.1; plan 005 §5.6.3, D-17): cada código
        de la validación tiene su fila con su nivel y su alcance; la regla bajo el límite se
        nombra por sus dos claves y no por la del plan anterior."""
        rows = {row[0].strip("`"): row for table in tables(section(self.text,
                                                                   "## 6. Validaciones"))
                for row in table if row and row[0].startswith("DH-")}
        self.assertEqual(sorted(rows), sorted(validate.CODES))
        for code, (level, scope) in validate.CODES.items():
            with self.subTest(code=code):
                self.assertEqual(rows[code][1:3],
                                 [LEVELS[str(level)], SCOPES[None if scope is None
                                                             else str(scope)]])
        named = set(backticked(self.text))
        for key in dh_params.BELOW_DL_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, named)
        self.assertNotIn("dh.below_dl_policy", self.text)

    def test_issue_levels_and_trace_columns(self) -> None:
        """RF-005-18, RF-005-20, RF-005-21 (T56; T59, F-4 de la verificación): el comentario de
        ``level`` de ``dh_validation_issue`` nombra cada nivel de ``drillholes.validate.Level``
        (también ``info``, la diferencia de una boca con el MDT, y ``not_evaluated``, una boca
        fuera de él); el de ``length_m`` de ``dh_trace`` dice que es una profundidad (la del
        último nodo, ``drillholes.jobs.trace_rows``), no la longitud de la polilínea; y la traza
        guardada no tiene vértices en los límites de los tramos (``trace_rows`` densifica sin
        profundidades de más; las tienen las curvas de la vista)."""
        columns = documented_columns(self.text)
        (level,) = [comment for code, comment in columns["dh_validation_issue"]
                    if code.startswith("level ")]
        words = set(re.findall(r"[a-z_]+", level))
        for value in validate.Level:
            with self.subTest(level=str(value)):
                self.assertIn(str(value), words)
        (length,) = [comment for code, comment in columns["dh_trace"]
                     if code.startswith("length_m ")]
        self.assertIn("profundidad", length)
        self.assertNotIn("polilínea", length)
        trace = SQL_FENCE.sub("", section(self.text, "### 4.1 `dh_trace`"))
        self.assertIsNone(VERTICES_AT_INTERVALS.search(trace))
        issues = SQL_FENCE.sub("", section(self.text, "### 4.2 `dh_validation_issue`"))
        self.assertNotIn("solo el informe de la operación", issues)


@docs.requires_docs
class ProjectFormatDocTest(unittest.TestCase):
    """``formato-proyecto.md`` §3.11 nombra las tablas de los sondeos."""

    def test_module_tables(self) -> None:
        """RF-005-01, RF-005-11 (plan 005 §5.6.1, D17): la fila ``dh_`` de §3.11 nombra cada
        tabla de la base y de lo calculado, y lo importado de cada papel como
        ``dh_src_<rol>_<nombre>_<entrada8>``."""
        modules = section(docs.read(FORMAT_RELPATH), "### 3.11 Tablas de los módulos")
        row = next(row for table in tables(modules) for row in table
                   if row and row[0] == "`dh_`")
        named = set(backticked(" ".join(row)))
        for name in (*schema.BASE_TABLES, *schema.COMPUTED_TABLES):
            with self.subTest(table=name):
                self.assertIn(name, named)
        for role in schema.SOURCE_ROLES:
            with self.subTest(role=role):
                self.assertIn(f"dh_src_{role}{SOURCE_SUFFIX}", named)


@docs.requires_docs
class UserGuideDocTest(unittest.TestCase):
    """La guía de uso de los sondeos (``docs/usuario/sondeos.md``) dice lo que hace el código
    (T59; F-4 de la verificación de la 005)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(GUIDE_RELPATH)
        cls.catalog = core_catalog.load()

    def test_import_a_file_by_extension(self) -> None:
        """RF-005-05, RF-005-06, RF-005-13 (T59; F-4 de la verificación: la guía y el CHANGELOG
        decían que un ``.csv`` o un ``.txt`` en «Importar un fichero…» abría el asistente de los
        sondeos, y abre el de los puntos de la 006): la tabla de §3.7 da, para cada extensión,
        la etiqueta de la orden que abre ``bl/ops/io.py`` (``tests.support.io_routes``), con
        todas las que abren un importador de los sondeos; la fila de «Importar un fichero…» de
        la tabla de las órdenes, el resto de la guía y la entrada de los sondeos del CHANGELOG
        del código solo le atribuyen al importador de los sondeos esas extensiones."""
        routes = io_routes.import_routes()
        to_drillholes = sorted(extension for extension, opens in routes.items()
                               if opens[0].startswith(DH_COMMAND))
        self.assertTrue(to_drillholes)
        (rows,) = tables(section(self.text, IMPORT_FILE_HEADING))
        documented: dict[str, str] = {}
        for extensions, opens, *_rest in rows:
            label = re.search(r"«([^»]+)»", opens)
            for extension in backticked(extensions):
                documented[extension] = "" if label is None else label.group(1)
        self.assertEqual(documented, {extension: io_routes.label_es(routes[extension][0])
                                      for extension in documented if extension in routes})
        self.assertLessEqual(set(to_drillholes), set(documented))
        row = next(row for table in tables(self.text) for row in table
                   if row and row[0] == IMPORT_ROW)
        said = {"tabla de las órdenes": [token for token in backticked(" ".join(row))
                                         if token.startswith(".")],
                "guía": mentioned_extensions(self.text),
                "CHANGELOG": mentioned_extensions(changelog_drillholes())}
        self.assertTrue(said["guía"])
        self.assertTrue(said["CHANGELOG"])
        for where, extensions in said.items():
            for extension in extensions:
                with self.subTest(donde=where, extension=extension):
                    self.assertIn(extension, to_drillholes)

    def test_what_is_still_greyed_out(self) -> None:
        """RF-005-01 (spec 003, RF-003-06; T59, F-4: faltaba «Exportar ▸ Muestras y
        compuestos…», de R-70): el párrafo «Lo demás del menú…» nombra la entrada del roadmap
        de cada orden del menú «Sondeos» que la 005 no entrega, y ninguna otra."""
        pending = {command.entry for command in menu_commands(self.catalog, DH_MENU)
                   if not delivered(self.catalog, command)}
        paragraph = next(paragraph for paragraph in self.text.split("\n\n")
                         if paragraph.startswith("Lo demás del menú"))
        self.assertEqual(sorted(set(re.findall(r"R-\d+", paragraph))), sorted(pending))

    def test_roles_and_their_columns(self) -> None:
        """RF-005-05 (T59; F-4: «Profundidad» no es obligatoria en las bocas, la litología no
        tiene «esquema de logueo» y la unidad de unos análisis en filas no es obligatoria): la
        tabla de §3.1 tiene una fila por papel (``interop.drillholes_tabular.ROLE_LABELS``, en
        su orden); antes del primer «;», los campos obligatorios del papel, en su orden (y, en
        los análisis en columnas, una columna por elemento); después, «opcionales» y solo
        campos opcionales del papel: todos, salvo si la lista acaba en «…»."""
        (rows,) = tables(section(self.text, ROLES_HEADING))
        self.assertEqual([row[0] for row in rows],
                         [tabular.ROLE_LABELS[role] for role in tabular.TableRole])
        for role, row in zip(tabular.TableRole, rows, strict=True):
            required, _, rest = row[1].partition(";")
            fields = list(tabular.aliases(role))
            mandatory = tabular.required_fields(role)
            expected = [field_label(str(role), field) for field in mandatory]
            if role is tabular.TableRole.ASSAY_WIDE:
                expected.append(EACH_ELEMENT)
            with self.subTest(role=str(role)):
                self.assertEqual(list_items(required)[0], expected)
                optional = [field_label(str(role), field) for field in fields
                            if field not in mandatory]
                rest = rest.strip()
                self.assertTrue(rest.startswith("opcionales ") or not optional, rest)
                named, open_ended = list_items(rest.removeprefix("opcionales "))
                self.assertEqual([item for item in named if item not in optional], [])
                if not open_ended:
                    self.assertEqual(sorted(named), sorted(optional))

    def test_levels_of_the_validation_list(self) -> None:
        """RF-005-16, RF-005-18 (T56; T59: faltaba «Información»): §5.2 nombra cada nivel de la
        lista de la validación en español, los del CSV (``drillholes.report``), y §5.3 dice que
        el CSV lleva la fila de cada boca con el MDT."""
        validation = one_line(section(self.text, "### 5.2 Validar"))
        for level in validate.Level:
            name = i18n.translate("es", dh_report._LEVELS[level])
            with self.subTest(level=str(level)):
                self.assertIn(name, validation)
        self.assertIn("MDT", section(self.text, "### 5.3 Exportar el informe"))

    def test_where_each_thing_is(self) -> None:
        """RF-005-01, RF-005-11, RF-008-53 (T59; F-4: los originales están en
        ``originals/<input_uid>/``): §13 nombra cada tabla de la base y de lo calculado, lo
        importado como ``dh_src_<rol>_<nombre>_<entrada8>`` y la carpeta de los originales."""
        named = set(backticked(section(self.text, "## 13. Dónde queda cada cosa")))
        for name in (*schema.BASE_TABLES, *schema.COMPUTED_TABLES,
                     f"dh_src_<rol>{SOURCE_SUFFIX}", "originals/<input_uid>/"):
            with self.subTest(name=name):
                self.assertIn(name, named)

    def test_traces_and_what_makes_them_stale(self) -> None:
        """RF-005-21, RF-005-22 (T59; F-4 y O-6 de la verificación): la guía no pone vértices de
        la traza guardada en los límites de los tramos (solo las curvas de la vista los
        tienen), y ni la guía ni el CHANGELOG dicen que una traza queda obsoleta por «el método
        de un sondeo»: el método es de la operación (``drillholes.store.kept_traces``: con otro,
        se recalculan todas) y lo obsoleto por sondeo es la huella de su desviación
        (``drillholes.store.stale_holes``)."""
        traces = one_line(section(self.text, "## 6. Las trazas"))
        self.assertIsNone(VERTICES_AT_INTERVALS.search(traces))
        self.assertIn("se recalculan todas", traces)
        for where, text in (("guía", self.text), ("CHANGELOG", changelog_drillholes())):
            with self.subTest(donde=where):
                self.assertNotIn(STALE_BY_METHOD, one_line(text))


if __name__ == "__main__":
    unittest.main()
