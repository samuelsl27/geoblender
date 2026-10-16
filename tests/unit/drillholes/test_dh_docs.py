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

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
"""

from __future__ import annotations

import pkgutil
import re
import sqlite3
import unittest
from contextlib import closing

from tests.support import docs
from tests.support.bs_tables import backticked, section, tables
from tests.support.package import import_geoblender

drillholes = import_geoblender("drillholes")
schema = import_geoblender("drillholes.schema")
provenance = import_geoblender("drillholes.provenance")
dh_params = import_geoblender("drillholes.params")
dh_jobs = import_geoblender("drillholes.jobs")
validate = import_geoblender("drillholes.validate")
gpkg_base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")

DH_RELPATH = "docs/arquitectura/modulos/dh.md"
DATA_RELPATH = "docs/arquitectura/datos/sondeos.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
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


if __name__ == "__main__":
    unittest.main()
