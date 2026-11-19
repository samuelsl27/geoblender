# SPDX-License-Identifier: GPL-3.0-or-later
"""La cubicación frente a su documentación (spec 011, T31; plan 011 §5.1, §5.2 y §5.3; ADR-0027,
«Obliga a»).

Como la topografía (``tests/unit/gis/test_gis_docs.py``) y los sondeos
(``tests/unit/drillholes/test_dh_docs.py``), el código manda y la documentación lo describe;
estas pruebas avisan de que se separan:

- ``docs/arquitectura/modulos/res.md``: lo que nombra de ``reserves`` en su API existe en el
  código y la API nombra cada módulo del paquete; «Operaciones, datos y parámetros» nombra cada
  tipo de operación de ``reserves.provenance``, cada familia de datos (``res_vol_``…), cada
  parámetro de ``reserves.params`` (también la altura de banco, que no se registra) y cada
  familia de parámetros (ADR-0027);
- ``docs/arquitectura/datos/formato-proyecto.md``: §3.11, el SQL de la columna de materiales y
  de las tablas de una cubicación, de sus toneladas y de sus momentos, una vez cada una en un
  bloque ``sql``, igual que lo crea el código salvo los comentarios, los espacios y las comillas
  (las de una cubicación, con un nombre de ejemplo: ``res_vol_<nombre>_<vNN>``); §4.2, el nombre
  de la rejilla de diferencias, y §3.3, cada familia de parámetros; y cada clave ``'res.…'`` de
  sus ejemplos existe en la cubicación (T39);
- y, de la 016 (su T38), la ficha ``res.md`` dice la base de los acopios como entrada de la verificación de la 012
  (``reserves.compliance.lowest_base`` y la selección de ``reserves.compliance_store``, que ``test_constraints_docs``
  comprueba nombre a nombre): automática, con lo que no usa y su causa, el corte de terreno y el de acopios, y lo que guarda.

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
"""

from __future__ import annotations

import pkgutil
import re
import sqlite3
import unittest
from contextlib import closing

from tests.support import docs
from tests.support.bs_tables import backticked, section
from tests.support.package import import_geoblender

reserves = import_geoblender("reserves")
gpkg_base = import_geoblender("core.gpkg.base")
materials = import_geoblender("reserves.materials")
params = import_geoblender("reserves.params")
provenance = import_geoblender("reserves.provenance")
store = import_geoblender("reserves.store")
compliance_store = import_geoblender("reserves.compliance_store")
compliance = import_geoblender("reserves.compliance")

RES_RELPATH = "docs/arquitectura/modulos/res.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
RES_NAME = re.compile(r"^reserves(?:\.[A-Za-z_]\w*)+$")
SQL_FENCE = re.compile(r"^```sql\n(.*?)^```", re.MULTILINE | re.DOTALL)
COMMENT = re.compile(r"--[^\n]*")
RES_KEY = re.compile(r"'(res\.[\w.{}]+)'")
CREATE = re.compile(r"^\s*CREATE\s+TABLE\s+\"?(res_\w+)\"?", re.IGNORECASE)
# Las tablas de res, por su comienzo: la columna del proyecto y las tres de una cubicación.
TABLE_PREFIXES = ("res_materials", "res_vol_", "res_ton_", "res_stg_")


def resolves(dotted: str) -> bool:
    """``reserves.<módulo>[.<nombre>…]`` existe en el código."""
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
    """El SQL de una sentencia sin comentarios, sin comillas dobles y con los espacios reducidos
    (ninguno junto a paréntesis y comas)."""
    text = COMMENT.sub(" ", sql).replace('"', "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([(),])\s*", r"\1", text)
    return text.strip().rstrip(";").strip()


def documented_tables(document: str) -> dict[str, list[str]]:
    """Las sentencias ``CREATE TABLE res_…`` de los bloques ``sql`` del documento,
    normalizadas, por nombre."""
    found: dict[str, list[str]] = {}
    for block in SQL_FENCE.findall(document):
        for statement in COMMENT.sub(" ", block).split(";"):
            match = CREATE.match(statement)
            if match is not None:
                found.setdefault(match.group(1), []).append(normalized(statement))
    return found


def code_table(name: str) -> str:
    """El SQL con que el código crea la tabla ``name`` de ``res`` (normalizado)."""
    with closing(sqlite3.connect(":memory:")) as conn:
        gpkg_base.create_structure(conn)
        if name == materials.TABLE:
            conn.execute(materials.CREATE_TABLE)
        else:
            columns = (store.STAGE_TABLE_COLUMNS if name.startswith("res_stg_")
                       else store.TABLE_COLUMNS)
            gpkg_base.create_attribute_table(conn, name, columns, name)
        (sql,) = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
    return normalized(str(sql))


@docs.requires_docs
class ResModuleDocTest(unittest.TestCase):
    """``modulos/res.md`` nombra la API, las operaciones, los datos y los parámetros que
    existen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(RES_RELPATH)

    def test_named_api_exists(self) -> None:
        """RF-011-01 a RF-011-26 (plan 011 §5.1 y §5.3.1): todo lo que la API de la ficha nombra
        de ``reserves`` existe, y la API nombra cada módulo del paquete."""
        api = section(self.text, "## API pública")
        named = {token for token in backticked(api) if RES_NAME.match(token)}
        self.assertGreater(len(named), 40)
        self.assertEqual(sorted(name for name in named if not resolves(name)), [])
        for info in pkgutil.iter_modules(reserves.__path__):
            with self.subTest(module=info.name):
                self.assertTrue(any(name == f"reserves.{info.name}"
                                    or name.startswith(f"reserves.{info.name}.")
                                    for name in named))

    def test_operations_datasets_and_parameters(self) -> None:
        """RF-011-05, RF-011-11, RF-011-20, RF-011-21, RF-011-22 (plan 011 §5.2.1 a §5.2.3;
        ADR-0027): la ficha nombra cada tipo de operación, cada familia de datos, cada parámetro
        y cada familia de parámetros."""
        named = set(backticked(section(self.text, "## Operaciones, datos y parámetros")))
        for declared in provenance.OPERATION_TYPES:
            with self.subTest(operation=declared.op_type):
                self.assertIn(declared.op_type, named)
        for family in provenance.FAMILIES:
            with self.subTest(dataset=family.code):
                self.assertIn(f"res_{family.code}_<nombre>", named)
        self.assertIn(materials.TABLE, named)
        for definition in (*params.DEFINITIONS, params.BENCH_HEIGHT_DEF):
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, named)
        for family in params.FAMILIES:
            with self.subTest(family=family.pattern):
                self.assertIn(family.pattern, named)

    def test_the_base_of_the_stockpiles_is_told(self) -> None:
        """RF-012-21, RF-012-22, RF-012-24, RF-012-30, RF-012-31 (spec 012 0.5, diff de la 016; D-a a D-d; P-10; T38): la
        ficha dice la base de los acopios como entrada opcional de la verificación —automática (las detecciones al día hechas
        sobre la partida; con varias, la menor), con lo que no usa y su causa, el corte de terreno y el de acopios, la exención
        por posición y que sin acopios todo es como antes— con los papeles, las filas y la cifra que guarda, y todo eso existe."""
        api = section(self.text, "## API pública")
        for fact in ("`reserves.compliance.lowest_base`", "`reserves.compliance_store.select_bases`",
                     "`reserves.compliance_store.BaseSelection`", "`reserves.compliance_store.StockpileBase`",
                     "`reserves.compliance_store.SkippedDetection`", "`reserves.compliance_store.base_role(k)`",
                     "**Automática** (D-a)", "la **menor**", "**no usa** con su causa", "`Counts.CUT_TERRAIN`",
                     "**corte de terreno**", "**corte de acopios**", "`ZoneTotals.stockpile_cut_m3`",
                     "exención por **posición**, D-b", "la verificación es **la de siempre, bit a bit**",
                     "`stockpile_base_<k>`", "`stockpile_skipped`", "`stockpile_cut_m3`", "`res.check_stockpile_cut_m3`",
                     "`res.freeze_cut_terrain`", "**Limitación conocida**"):
            with self.subTest(fact=fact):
                self.assertIn(fact, api)
        self.assertEqual(compliance_store.base_role(2), "stockpile_base_2")
        self.assertEqual(compliance.Counts.CUT_TERRAIN.value, "cut_terrain")
        self.assertIn("stockpile_cut_m3", {field for field in compliance.ZoneTotals.__dataclass_fields__})
        self.assertIn("res.check_stockpile_cut_m3", {figure.key for figure in provenance.VERIFY_FIGURES})
        for field in ("selection", "start_name", "bases", "skipped"):
            with self.subTest(stored=field):
                self.assertIn(field, compliance_store.StoredVerification.__dataclass_fields__)
        owned = section(self.text, "## Datos que posee")
        for fact in ("`stockpile_base`", "`stockpile_skipped`", "`stockpile_cut_m3`", "`res.check_stockpile_cut_m3`"):
            with self.subTest(owned=fact):
                self.assertIn(fact, owned)
        self.assertIn("**el algoritmo, `reserves.compliance`, no importa `design`**", section(self.text,
                      "## Dependencias permitidas"))


@docs.requires_docs
class ProjectFormatDocTest(unittest.TestCase):
    """``formato-proyecto.md`` describe las tablas, la rejilla y los parámetros de ``res``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(FORMAT_RELPATH)

    def test_tables_as_in_the_code(self) -> None:
        """RF-011-11, RF-011-22 (plan 011 §5.2.1, D-27): §3.11 tiene una vez el SQL de cada
        tabla de ``res``, el que escribe el código."""
        documented = documented_tables(section(self.text, "### 3.11 Tablas de los módulos"))
        for prefix in TABLE_PREFIXES:
            with self.subTest(table=prefix):
                names = [name for name in documented
                         if name == prefix or (prefix.endswith("_") and name.startswith(prefix))]
                self.assertEqual(len(names), 1, f"{prefix}: {names}")
                (name,) = names
                self.assertEqual(documented[name], [code_table(name)])

    def test_difference_grid_and_parameter_families(self) -> None:
        """RF-011-05, RF-011-11, RF-011-21 (plan 011 §5.2.1, §5.2.2; ADR-0027, «Obliga a»): §4.2
        nombra la rejilla de diferencias de una cubicación y §3.3, cada familia de parámetros."""
        rasters = backticked(section(self.text, "### 4.2 `rasters/` — GeoTIFF"))
        self.assertEqual(provenance.dataset_locator("dif", "Mensual", "V03"),
                         "rasters/res_dif_mensual_v03.tif")
        self.assertIn("res_dif_<nombre>_<vNN>.tif", rasters)
        parameters = set(backticked(section(
            self.text, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados")))
        for family in params.FAMILIES:
            with self.subTest(family=family.pattern):
                self.assertIn(family.pattern, parameters)

    def test_res_keys_of_the_examples_exist(self) -> None:
        """RF-011-21, RF-011-22 (plan 011 §5.2.2 y §5.2.3; T39, verificación F-4): cada clave
        ``'res.…'`` de los ejemplos del formato (los comentarios del SQL de ``gb_parameter``,
        ``gb_figure``…) es un parámetro, una familia de parámetros, una cifra o un tipo de
        operación de la cubicación: no una clave que no existe (``'res.swell_factor'``)."""
        known = {definition.key for definition in (*params.DEFINITIONS,
                                                   params.BENCH_HEIGHT_DEF)}
        known |= {family.pattern for family in params.FAMILIES}
        known |= {figure.key for figure in provenance.FIGURES}
        known |= {declared.op_type for declared in provenance.OPERATION_TYPES}
        quoted = set(RES_KEY.findall(self.text))
        self.assertEqual(sorted(quoted - known), [])


if __name__ == "__main__":
    unittest.main()
