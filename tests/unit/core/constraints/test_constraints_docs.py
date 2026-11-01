# SPDX-License-Identifier: GPL-3.0-or-later
"""Los límites y las restricciones frente a su documentación (spec 012, T34; plan 012 §5.1,
§5.2, §5.3 y §5.6; ADR-0028).

Como la topografía (``tests/unit/gis/test_gis_docs.py``), la cubicación
(``tests/unit/reserves/test_res_docs.py``) y la procedencia
(``tests/unit/core/provenance/test_format_docs.py``), el código manda y la documentación lo
describe; estas pruebas avisan de que se separan:

- ``docs/arquitectura/modulos/core.md``: la API nombra cada módulo de ``core.constraints`` y cada
  clase y función pública que define; «Datos que posee» nombra sus siete tablas y la de estilos,
  y la ficha, sus operaciones y sus parámetros;
- ``docs/arquitectura/modulos/gis.md``: la API nombra cada clase y función pública de
  ``gis.masks`` (sus diez módulos), ``gis.search``, ``gis.polygons`` y ``gis.coverage``; la
  ficha dice su operación, sus datos y sus cifras;
- ``docs/arquitectura/modulos/res.md``: la API nombra cada clase y función pública de
  ``reserves.compliance`` y ``reserves.compliance_store``; la ficha dice su operación, sus
  datos, su parámetro y sus cifras;
- ``docs/arquitectura/datos/formato-proyecto.md``: §3.9 y §3.11 tienen una vez el SQL de cada
  tabla de la 012, igual que lo crea el código (salvo los comentarios, los espacios y las
  comillas); §3.3, cada familia de parámetros; §4.2, las rejillas de las máscaras y de los
  incumplimientos;
- la guía de uso ``docs/usuario/limites-y-restricciones.md`` nombra los once tipos, los seis
  roles y las órdenes de Diseño ▸ Límites y restricciones, y las guías que la citan la enlazan.

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
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
from tests.support.bs_tables import backticked, section
from tests.support.package import import_geoblender

constraints = import_geoblender("core.constraints")
cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cprov = import_geoblender("core.constraints.provenance")
cstore = import_geoblender("core.constraints.store")
cstyles = import_geoblender("core.constraints.styles")
gpkg_base = import_geoblender("core.gpkg.base")
masks = import_geoblender("gis.masks")
mprov = import_geoblender("gis.masks.provenance")
mstore = import_geoblender("gis.masks.store")
chk = import_geoblender("reserves.compliance_store")
catalog = import_geoblender("core.catalog")

CORE_RELPATH = "docs/arquitectura/modulos/core.md"
GIS_RELPATH = "docs/arquitectura/modulos/gis.md"
RES_RELPATH = "docs/arquitectura/modulos/res.md"
FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
GUIDE_RELPATH = "docs/usuario/limites-y-restricciones.md"
CITING_RELPATHS = ("docs/usuario/topografia.md", "docs/usuario/versiones.md",
                   "docs/usuario/cubicacion.md", "README.md")

# Los módulos de gis y de reserves de la 012 cuya API pública tiene que nombrar su ficha.
GIS_MODULES = ("gis.search", "gis.polygons", "gis.coverage",
               *(f"gis.masks.{info.name}" for info in pkgutil.iter_modules(masks.__path__)))
RES_MODULES = ("reserves.compliance", "reserves.compliance_store")
CORE_MODULES = tuple(f"core.constraints.{info.name}"
                     for info in pkgutil.iter_modules(constraints.__path__))
# De lo que la 012 declara, lo que no es una clase ni una función pero la ficha tiene que decir.
CORE_CONSTANTS = ("TABLES", "CONSTRAINT_LAYERS", "CTYPE_ENUM", "FAMILIES", "DEFINITIONS",
                  "SEARCH_DISTANCE", "OPERATIONS", "COLORS", "MESSAGES", "PROBLEMS")
# Las órdenes de Diseño ▸ Límites y restricciones que entrega la 012 (plan 012 D-31, D-38).
ORDERS = ("geoblender.core_edit_limits", "geoblender.core_edit_constraints",
          "geoblender.core_find_untouchables", "geoblender.core_edit_client_marks",
          "geoblender.core_toggle_constraints_overlay", "geoblender.gis_compile_constraints",
          "geoblender.res_verify_constraints")

SQL_FENCE = re.compile(r"^```sql\n(.*?)^```", re.MULTILINE | re.DOTALL)
FENCE = re.compile(r"^```[^\n]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
COMMENT = re.compile(r"--[^\n]*")
CREATE = re.compile(r"^\s*CREATE\s+TABLE\s+\"?(\w+)\"?", re.IGNORECASE)
DOTTED = re.compile(r"^(?:core|gis|reserves)(?:\.[A-Za-z_]\w*)+$")
# Las tablas de la 012 en formato-proyecto.md: cada una, por su comienzo (las de una versión
# llevan un nombre de ejemplo y el código de la versión).
PROJECT_TABLES = (*cstore.TABLES, cstyles.STYLES_TABLE)
VERSION_TABLES = ("gis_mskz_", "gis_mskr_", "gis_mskp_", "gis_mskg_", "res_chk_", "res_chkg_")


def public_api(dotted: str) -> list[str]:
    """Las clases y las funciones de ``__all__`` que define el módulo ``dotted`` (no lo que
    importa de otro)."""
    module = import_geoblender(dotted)
    found = []
    for name in getattr(module, "__all__", ()):
        obj = getattr(module, name)
        if (inspect.isclass(obj) or inspect.isfunction(obj)) and obj.__module__ == module.__name__:
            found.append(name)
    return found


def resolves(dotted: str) -> bool:
    """``<paquete>.<módulo>[.<nombre>…]`` existe en el código."""
    parts = dotted.split(".")
    for cut in range(len(parts), 1, -1):
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


def inline_tokens(text: str) -> set[str]:
    """Los textos entre comillas invertidas de ``text`` sin sus bloques de código: las tres
    comillas de una valla desalinean el emparejamiento de las que siguen."""
    return set(backticked(FENCE.sub(" ", text)))


def names_of(text: str) -> set[str]:
    """Los nombres con puntos que ``text`` pone entre comillas invertidas, con o sin la firma
    que los sigue (``core.constraints.checks.incomplete(constraints, resolved)`` es
    ``core.constraints.checks.incomplete``)."""
    found = set()
    for token in backticked(text):
        name = re.split(r"[(\s]", token, maxsplit=1)[0]
        if DOTTED.match(name):
            found.add(name)
    return found


def named_in(text: str, prefix: str) -> set[str]:
    """Los nombres de ``names_of(text)`` que son de ``prefix`` (``core.constraints``…)."""
    return {name for name in names_of(text) if name == prefix or name.startswith(prefix + ".")}


def missing_names(text: str, modules: Iterable[str]) -> list[str]:
    """Lo público de ``modules`` que ``text`` no nombra como ``<módulo>.<nombre>``."""
    tokens = names_of(text)
    return sorted(f"{dotted}.{name}" for dotted in modules for name in public_api(dotted)
                  if f"{dotted}.{name}" not in tokens)


def normalized(sql: str) -> str:
    """El SQL de una sentencia sin comentarios, sin comillas dobles y con los espacios
    reducidos (ninguno junto a paréntesis y comas)."""
    text = COMMENT.sub(" ", sql).replace('"', "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([(),])\s*", r"\1", text)
    return text.strip().rstrip(";").strip()


def documented_tables(document: str) -> dict[str, list[str]]:
    """Las sentencias ``CREATE TABLE`` de los bloques ``sql`` del documento, normalizadas,
    por nombre."""
    found: dict[str, list[str]] = {}
    for block in SQL_FENCE.findall(document):
        for statement in COMMENT.sub(" ", block).split(";"):
            match = CREATE.match(statement)
            if match is not None:
                found.setdefault(match.group(1), []).append(normalized(statement))
    return found


def code_tables() -> dict[str, str]:
    """El SQL con que el código crea cada tabla de la 012 (normalizado), con un nombre de
    ejemplo para las de una versión."""
    with closing(sqlite3.connect(":memory:")) as conn:
        gpkg_base.create_structure(conn)
        conn.execute("INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
                     "organization_coordsys_id, definition) VALUES ('t', 25830, 'EPSG', 25830, "
                     "'x')")
        cstore.create_tables(conn, 25830)
        mstore._create(conn, mprov.ZONES, "gis_mskz_v01", 25830, "z")
        mstore._create(conn, mprov.REPORT, "gis_mskr_v01", 25830, "r")
        mstore._create(conn, mprov.PARTS, "gis_mskp_v01", 25830, "p")
        mstore._create(conn, mprov.SHAPES, "gis_mskg_v01", 25830, "g")
        chk._create(conn, chk.TABLE, "res_chk_verificacion_v01", 25830, "c")
        chk._create(conn, chk.GROUPS, "res_chkg_verificacion_v01", 25830, "d")
        conn.execute(cstyles._STYLES_DDL)
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    wanted = (*cstore.TABLES, cstyles.STYLES_TABLE, "gis_mskz_v01", "gis_mskr_v01",
              "gis_mskp_v01", "gis_mskg_v01", "res_chk_verificacion_v01",
              "res_chkg_verificacion_v01")
    return {str(name): normalized(str(sql)) for name, sql in rows if name in wanted}


@docs.requires_docs
class CoreModuleDocTest(unittest.TestCase):
    """``modulos/core.md`` nombra la API, las tablas, las operaciones y los parámetros de
    ``core.constraints``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(CORE_RELPATH)
        cls.api = section(cls.text, "## API pública")

    def test_named_api_exists_and_is_complete(self) -> None:
        """RF-012-01 a RF-012-10, RF-012-26, RF-012-27 (plan 012 §5.1 y §5.3.1): todo lo que la
        ficha nombra de ``core.constraints`` existe, nombra cada módulo del paquete y cada clase
        y función pública que define, y las constantes de :data:`CORE_CONSTANTS` de su módulo."""
        named = named_in(self.api, "core.constraints")
        self.assertGreater(len(named), 70)
        self.assertEqual(sorted(name for name in named if not resolves(name)), [])
        self.assertEqual(len(CORE_MODULES), 7)
        for dotted in CORE_MODULES:
            with self.subTest(module=dotted):
                self.assertIn(dotted, named)
        self.assertEqual(missing_names(self.api, CORE_MODULES), [])
        tokens = names_of(self.api)
        for dotted in CORE_MODULES:
            module = import_geoblender(dotted)
            for name in CORE_CONSTANTS:
                if name in getattr(module, "__all__", ()):
                    with self.subTest(constant=f"{dotted}.{name}"):
                        self.assertIn(f"{dotted}.{name}", tokens)

    def test_owned_tables_operations_and_parameters(self) -> None:
        """RF-012-02, RF-012-06, RF-012-09, RF-012-16, RF-012-26 (plan 012 §5.2.1 y §5.2.2;
        ADR-0027): «Datos que posee» nombra las siete tablas y la de estilos, y la ficha, cada
        tipo de operación de ``core.constraints.provenance``, cada familia de parámetros y la
        distancia de búsqueda."""
        owned = set(backticked(section(self.text, "## Datos que posee")))
        for table in PROJECT_TABLES:
            with self.subTest(table=table):
                self.assertIn(table, owned)
        self.assertIn(cstyles.STYLES_DATASET, owned)
        named = set(backticked(self.text))
        for declared in cprov.OPERATIONS:
            with self.subTest(operation=declared.op_type):
                self.assertIn(declared.op_type, named)
        for family in cparams.FAMILIES:
            with self.subTest(family=family.pattern):
                self.assertIn(family.pattern, named)
        for definition in cparams.DEFINITIONS:
            with self.subTest(parameter=definition.key):
                self.assertIn(definition.key, named)


@docs.requires_docs
class GisModuleDocTest(unittest.TestCase):
    """``modulos/gis.md`` nombra la API, la operación, los datos y las cifras de las máscaras."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(GIS_RELPATH)
        cls.api = section(cls.text, "## API pública")

    def test_named_api_is_complete(self) -> None:
        """RF-012-05, RF-012-08, RF-012-11 a RF-012-17, RF-012-20 (plan 012 §5.1 y §5.3.1;
        ADR-0028): la API de la ficha nombra cada clase y función pública de los diez módulos de
        ``gis.masks``, de ``gis.search``, ``gis.polygons`` y ``gis.coverage``."""
        self.assertEqual(len(GIS_MODULES), 13)
        self.assertEqual(missing_names(self.api, GIS_MODULES), [])
        tokens = names_of(self.api)
        for dotted in GIS_MODULES:
            with self.subTest(module=dotted):
                self.assertTrue(any(token == dotted or token.startswith(dotted + ".")
                                    for token in tokens))

    def test_operation_datasets_and_figures(self) -> None:
        """RF-012-11, RF-012-16 (plan 012 §5.2.3, D-24; ADR-0028): la ficha nombra la operación
        ``gis.compile_constraints``, cada familia de datos de las máscaras con su nombre, sus
        cifras y el papel «entidades» que alimenta las capas de la 012."""
        named = set(backticked(section(self.text, "## Operaciones, datos y parámetros")))
        self.assertIn(mprov.COMPILE, named)
        for family in mprov.FAMILIES:
            with self.subTest(dataset=family.code):
                self.assertIn(f"gis_{family.code}_<vNN>", named)
        for figure in mprov.FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, named)
        for name in ("gis_fea_<slug>", "gis.vector.FeatureLayer", "gis.store.feature_pieces"):
            with self.subTest(name=name):
                self.assertIn(name, set(backticked(self.text)))


@docs.requires_docs
class ResModuleDocTest(unittest.TestCase):
    """``modulos/res.md`` nombra la API, la operación, los datos y el parámetro de la
    verificación por recinto."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(RES_RELPATH)

    def test_named_api_is_complete(self) -> None:
        """RF-012-21 a RF-012-25 (plan 012 §5.3.1, A7–A11): la API de la ficha nombra cada clase
        y función pública de ``reserves.compliance`` y ``reserves.compliance_store``."""
        api = section(self.text, "## API pública")
        self.assertEqual(missing_names(api, RES_MODULES), [])

    def test_operation_datasets_parameter_and_figures(self) -> None:
        """RF-012-21, RF-012-24 (plan 012 §5.2.3, D-28, D-42): la ficha nombra la operación
        ``res.verify_constraints``, sus tres familias de datos, el espesor mínimo y cada cifra."""
        named = set(backticked(section(self.text, "## Operaciones, datos y parámetros")))
        self.assertIn(chk.VERIFY, named)
        self.assertIn("res_chk_<nombre>", named)
        self.assertIn("res_chkg_<nombre>", named)
        self.assertIn("res_chkv_<nombre>_<k>", named)
        self.assertIn(chk.MIN_THICKNESS, named)
        for figure in chk.FIGURES:
            with self.subTest(figure=figure.key):
                self.assertIn(figure.key, named)


@docs.requires_docs
class ProjectFormatDocTest(unittest.TestCase):
    """``formato-proyecto.md`` describe las tablas, las rejillas y los parámetros de la 012."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(FORMAT_RELPATH)

    def test_tables_as_in_the_code(self) -> None:
        """RF-012-01, RF-012-02, RF-012-07, RF-012-09, RF-012-11, RF-012-21, RF-012-23,
        RF-012-26 (plan 012 §5.2.1 y §5.2.3, D-32): §3.9 y §3.11 tienen una vez el SQL de cada
        tabla del proyecto de la 012 y de cada una de la versión (máscaras y verificación),
        el que escribe el código."""
        documented = documented_tables(section(self.text, "### 3.9 Restricciones y límites")
                                       + section(self.text, "### 3.11 Tablas de los módulos"))
        in_code = code_tables()
        for table in PROJECT_TABLES:
            with self.subTest(table=table):
                self.assertEqual(documented.get(table, []), [in_code[table]])
        for prefix in VERSION_TABLES:
            with self.subTest(table=prefix):
                names = [name for name in documented if name.startswith(prefix)]
                self.assertEqual(len(names), 1, f"{prefix}: {names}")
                (name,) = names
                self.assertEqual(documented[name], [in_code[name]])

    def test_types_roles_and_labels(self) -> None:
        """RF-012-02, RF-012-26 (plan 012 §5.2.1, D-16, D-23): §3.9 dice, cada una en su
        tabla, los once tipos con su código y su nombre en español, y los seis roles de una
        marca del cliente con su código."""
        text = section(self.text, "### 3.9 Restricciones y límites")
        tokens = inline_tokens(text)
        for ctype in cmodel.ConstraintType:
            with self.subTest(ctype=ctype.value):
                self.assertIn(ctype.value, tokens)
                self.assertIn(ctype.label("es"), text)
        for role in cmodel.IntentionRole:
            with self.subTest(role=role.value):
                self.assertIn(role.value, tokens)

    def test_rasters_and_parameter_families(self) -> None:
        """RF-012-02, RF-012-11, RF-012-23 (plan 012 §5.2.2 y §5.2.3; ADR-0027, «Obliga a»):
        §4.2 nombra la rejilla de clases de las máscaras y las de incumplimientos de una
        verificación, y §3.3 dice cada familia de parámetros de una restricción, la distancia
        de búsqueda y el espesor mínimo de la verificación."""
        self.assertEqual(mprov.dataset_locator(mprov.CLASSES, "V01"), "rasters/gis_msk_v01.tif")
        self.assertEqual(chk.dataset_locator(chk.VIOLATIONS, "Mi diseño", "V01", 2),
                         "rasters/res_chkv_mi_diseno_2_v01.tif")
        rasters = inline_tokens(section(self.text, "### 4.2 `rasters/` — GeoTIFF"))
        self.assertIn("gis_msk_<vNN>.tif", rasters)
        self.assertIn("res_chkv_<nombre>_<k>_<vNN>.tif", rasters)
        parameters = inline_tokens(section(
            self.text, "### 3.3 `gb_parameter` y `gb_parameter_history` — parámetros tipados"))
        for family in cparams.FAMILIES:
            with self.subTest(family=family.pattern):
                self.assertIn(family.pattern, parameters)
        for key in (cparams.SEARCH_DISTANCE.key, chk.MIN_THICKNESS):
            with self.subTest(key=key):
                self.assertIn(key, parameters)


@docs.requires_docs
class GuideDocTest(unittest.TestCase):
    """La guía de uso de los límites y las restricciones."""

    def test_guide_names_types_roles_and_orders(self) -> None:
        """RF-012-02, RF-012-26, RF-012-28 (spec 012 §2 y §7): la guía nombra, con el texto de
        la interfaz, los once tipos de restricción, los seis roles de una marca del cliente y
        cada orden de Diseño ▸ Límites y restricciones que entrega la 012."""
        text = docs.read(GUIDE_RELPATH)
        for ctype in cmodel.ConstraintType:
            with self.subTest(ctype=ctype.value):
                self.assertIn(ctype.label("es"), text)
        for role in cmodel.IntentionRole:
            with self.subTest(role=role.value):
                self.assertIn(role.label("es"), text)
        cat = catalog.load()
        for key in ORDERS:
            with self.subTest(order=key):
                self.assertIn(cat.commands[key].label_es, text)

    def test_guides_that_cite_it_link_it(self) -> None:
        """RF-012-01, RF-012-21, RF-012-25 (plan 012 §5.6; T34): la topografía (el papel
        «entidades»), las versiones (congelar), la cubicación (verificar) y el README enlazan la
        guía."""
        for relpath in CITING_RELPATHS:
            with self.subTest(document=relpath):
                self.assertIn("limites-y-restricciones.md", docs.read(relpath))


if __name__ == "__main__":
    unittest.main()
