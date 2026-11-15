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
  roles y las órdenes de Diseño ▸ Límites y restricciones, y las guías que la citan la enlazan;
- los ocho puntos de F-5 de la verificación única (T43): la guía, el índice de specs, el roadmap,
  las fichas de ``core``, ``gis`` y ``res``, el formato del proyecto y el ``CHANGELOG.md`` del
  código dicen lo que el código hace tras la T38 a la T42 (``ConvergenceDocTest``).

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
from tests.support.repo import ROOT

constraints = import_geoblender("core.constraints")
cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cprov = import_geoblender("core.constraints.provenance")
cstore = import_geoblender("core.constraints.store")
cstyles = import_geoblender("core.constraints.styles")
gpkg_base = import_geoblender("core.gpkg.base")
cmessages = import_geoblender("core.constraints.messages")
i18n = import_geoblender("core.i18n")
rprov = import_geoblender("reserves.provenance")
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
SPECS_INDEX_RELPATH = docs.SPECS_INDEX_RELPATH
ROADMAP_RELPATH = docs.ROADMAP_RELPATH
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
CITING_RELPATHS = ("docs/usuario/topografia.md", "docs/usuario/versiones.md",
                   "docs/usuario/cubicacion.md", "README.md")

# Los módulos de gis y de reserves de la 012 cuya API pública tiene que nombrar su ficha.
GIS_MODULES = ("gis.search", "gis.polygons", "gis.coverage",
               *(f"gis.masks.{info.name}" for info in pkgutil.iter_modules(masks.__path__)))
RES_MODULES = ("reserves.compliance", "reserves.compliance_store")
# Los módulos de ``core.constraints`` que la spec 015 añade mientras se construye: la ficha
# ``core.md`` (la API de ``core.constraints`` y «Datos que posee», la tabla ``des_decl_<vNN>``) los
# describe en su T34 (documentación), que vacía esto. Cada tarea de la 015 añade aquí lo suyo.
PENDING_015_MODULES = frozenset({
    "core.constraints.declared",  # T16: la restricción declarada por una entidad (RF-012-29)
})
# Lo que la spec 015 añade a la API pública de módulos que ya tienen ficha (``gis.md``, «API pública»)
# mientras se construye: la T34 (documentación) lo lleva a la ficha y vacía esto.
PENDING_015_API = frozenset({
    "gis.masks.provenance.declared_resolved",  # T18: las columnas de una declarada bajo las claves
})
CORE_MODULES = tuple(f"core.constraints.{info.name}"
                     for info in pkgutil.iter_modules(constraints.__path__)
                     if f"core.constraints.{info.name}" not in PENDING_015_MODULES)
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
                  if f"{dotted}.{name}" not in tokens
                  and f"{dotted}.{name}" not in PENDING_015_API)


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


def one_line(text: str) -> str:
    """``text`` con cada salto de línea y sangría reducidos a un espacio, para buscar una frase
    que el documento parte en dos renglones."""
    return re.sub(r"\s+", " ", text)


@docs.requires_docs
class ConvergenceDocTest(unittest.TestCase):
    """Los ocho puntos de F-5 de la verificación única de la 012 (T43; definición de hecho
    §3.7): la documentación dice lo que el código hace tras la T38 a la T42."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = docs.read(GUIDE_RELPATH)

    def guide_section(self, heading: str) -> str:
        return one_line(section(self.guide, heading))

    def test_guide_gives_the_budget_of_a_call_not_of_a_step(self) -> None:
        """RNF-012-06 (F-5, punto 1): la guía no promete «pasos de menos de 0,05 s» —el
        presupuesto de trabajo de un paso—, sino el RNF, ≤ 0,2 s por llamada (en Blender se miden
        0,03 a 0,16 s), y dice que lo que no se trocea es la transacción final y «Recalcular lo
        obsoleto» (0,40 a 0,55 s por llamada)."""
        text = self.guide_section("## 13. Mientras calcula, Esc y solo lectura")
        self.assertNotIn("pasos de menos de 0,05 s", self.guide)
        self.assertIn("0,2 s", text)
        self.assertIn("0,03 a 0,16 s", text)
        self.assertIn("Recalcular lo obsoleto", text)
        self.assertIn("0,40 a 0,55 s", text)

    def test_guide_says_papel_like_the_interface(self) -> None:
        """RF-012-26 (F-5, punto 2): la guía llama «papel» a lo que la interfaz llama «papel»
        («Papel de las marcas», «Campo del papel», «Valores del papel») y no «rol»."""
        text = self.guide_section("## 8. Las intenciones del cliente")
        for msgid in ("Role of the marks", "Role field", "Values of the role"):
            with self.subTest(msgid=msgid):
                self.assertIn(i18n.translate("es", msgid), text)
        self.assertIsNone(re.search(r"\brol(?:es)?\b", self.guide, re.IGNORECASE))

    def test_guide_says_which_legal_limit_buffer_rules(self) -> None:
        """RF-012-02, RF-012-13 (F-5, punto 3; observación O-6; T44, hallazgo F-1): con varios
        límites legales el límite legal es su unión y manda el mayor resguardo hacia dentro, en
        todo el contorno; la zona de cada uno son las celdas enteras dentro de su polígono (900 m²
        las dos concesiones del ejemplo, no 1.800 m²) y su banda hacia dentro cuenta cada celda
        una sola vez. La guía ya no dice «Hoy, además» ni que está pendiente de decidir."""
        limits = self.guide_section("## 4. Los límites")
        self.assertIn("el **mayor** de los resguardos hacia dentro", limits)
        self.assertIn("todo el contorno", limits)
        self.assertIn("su **unión**", limits)
        self.assertIn("la zona de cada límite legal", limits)
        self.assertIn("celdas enteras dentro de **su** polígono", limits)
        self.assertIn("900 m² cada una", limits)
        self.assertIn("una sola vez", limits)
        self.assertIn("un solo recinto", limits)
        self.assertIn("Recalcular lo obsoleto", limits)
        for stale in ("Hoy, además", "pendiente de decidir", "1.800 m² cada una"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, limits)
        types = self.guide_section("### 5.1 Los once tipos")
        self.assertIn("con varios límites legales manda el mayor", types)

    def test_guide_says_a_constraint_without_cells_is_not_in_the_verification(self) -> None:
        """RF-012-22 (F-5, punto 4; observación O-3): «No entra en la verificación» es lo que
        enseña una restricción nueva y también una activa que no tiene ninguna celda en la
        rejilla."""
        text = self.guide_section("## 10. Verificar un diseño por recinto")
        row = re.search(r"\| \*\*No entra en la verificación\*\* \|([^|]*)\|", text)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("ninguna celda en la rejilla", row.group(1))
        self.assertEqual(i18n.translate("es", "Not in the verification"),
                         "No entra en la verificación")

    def test_guide_says_the_cell_tolerance_of_a_utm(self) -> None:
        """RF-012-12 (T39; D-37): la guía dice que el redondeo de las coordenadas de un UTM no
        añade un anillo de celdas a un límite alineado con la rejilla."""
        text = self.guide_section("## 6. Compilar las máscaras")
        self.assertIn("1 µm", text)
        self.assertIn("redondeo", text)

    def test_decision_link_is_told_where_it_is_set(self) -> None:
        """RF-012-02, RF-012-19, RF-012-27 (F-5, punto 7; T41): la guía y el formato del proyecto
        dicen que la decisión enlazada se fija en «Desde una capa…» y en «Completar…» (campo
        «Decisión de la propiedad»), que una que no está registrada se rechaza, y que «Convertir
        en restricción…» hereda la de la intención."""
        label = i18n.translate("es", "Decision of the owner")
        self.assertEqual(label, "Decisión de la propiedad")
        code = "core.constraint_decision_unknown"
        self.assertIn(code, cmessages.MESSAGES)
        for heading in ("### 5.2 Crear restricciones desde una capa",
                        "### 5.3 Completar y editar"):
            with self.subTest(heading=heading):
                self.assertIn(label, self.guide_section(heading))
        converting = self.guide_section("## 8. Las intenciones del cliente")
        self.assertIn("hereda la decisión de la propiedad de la intención", converting)
        searched = self.guide_section("## 7. Buscar los elementos intocables por sector")
        self.assertIn("no enlaza ninguna decisión de la propiedad", searched)
        shown = self.guide_section("## 9. Ver las restricciones y los límites")
        self.assertIn("«Desde una capa…» o «Completar…»", shown)
        fmt = one_line(section(docs.read(FORMAT_RELPATH), "### 3.9 Restricciones y límites"))
        self.assertIn(label, fmt)
        self.assertIn(code, fmt)
        self.assertIn("«Convertir en restricción…» hereda la de la intención", fmt)

    def test_module_cards_say_where_the_registries_live(self) -> None:
        """RNF-001-03, RF-012-25 (F-5, punto 6; T38): ``core.md`` dice que el registro de
        comprobaciones de congelar vive en ``core.versions.freezing`` y ``res.md``, que las
        declaraciones de la verificación están en ``reserves.provenance``."""
        core = names_of(docs.read(CORE_RELPATH))
        for name in ("register_freeze_check", "unregister_freeze_checks", "freeze_checks"):
            with self.subTest(name=name):
                self.assertIn(f"core.versions.freezing.{name}", core)
        res = names_of(docs.read(RES_RELPATH))
        declared = [name for name in rprov.__all__
                    if name.startswith("VERIFY") or name == "verify_operation_def"]
        self.assertEqual(len(declared), 8)
        for name in declared:
            with self.subTest(name=name):
                self.assertIn(f"reserves.provenance.{name}", res)

    def test_gis_card_names_the_cell_tolerance_and_the_bands(self) -> None:
        """RF-012-12, RF-012-15 (T39, T40): la ficha de ``gis`` nombra la tolerancia por rejilla
        (``noise_m``, ``fraction_epsilon``, ``distance_tau``) y lo que recorre una restricción
        mayor que la rejilla por bandas (``touched_runs``, ``band_spans``)."""
        api = names_of(section(docs.read(GIS_RELPATH), "## API pública"))
        for name in ("gis.masks.zones.noise_m", "gis.masks.zones.fraction_epsilon",
                     "gis.masks.zones.distance_tau", "gis.masks.zones.touched_runs",
                     "gis.coverage.band_spans"):
            with self.subTest(name=name):
                self.assertIn(name, api)
                self.assertTrue(resolves(name))

    def test_indexes_reach_the_last_task(self) -> None:
        """Definición de hecho §3.7 (F-5, punto 5): el índice de specs y el roadmap dicen que la
        012 llega a la T46, que habilitar mide 0,45 s y que ``check.py`` tarda 40,5 s, y que la
        llamada más larga de cada orden no cuenta la transacción final ni «Recalcular lo
        obsoleto» (0,40 a 0,55 s)."""
        index = docs.read(SPECS_INDEX_RELPATH)
        roadmap = docs.read(ROADMAP_RELPATH)
        start = index.index("**La 012**")
        paragraph = one_line(index[start:index.index("- **Lo que queda de personas en la 012:**")])
        row = re.search(r"^\| 012 \|.*$", index, re.MULTILINE)
        ledger = re.search(r"^\| R-32 \|.*$", roadmap, re.MULTILINE)
        self.assertIsNotNone(row)
        self.assertIsNotNone(ledger)
        assert row is not None and ledger is not None
        self.assertIn("46 (T01–T46)", row.group(0))
        for name, text in (("índice", paragraph), ("fila del índice", row.group(0)),
                           ("roadmap", ledger.group(0))):
            with self.subTest(document=name):
                self.assertIn("T01 a T46", text)
        self.assertNotIn("T01 a T37", index)
        self.assertNotIn("T01 a T37", roadmap)
        for fact in ("0,45 s", "40,5 s", "Recalcular lo obsoleto", "0,40–0,55 s", "30–160 ms"):
            with self.subTest(fact=fact):
                self.assertIn(fact, paragraph)

    def test_changelog_says_the_single_verification_and_what_stays_open(self) -> None:
        """Definición de hecho §3.7 (F-5, punto 8; T44, hallazgo F-1): el ``CHANGELOG.md`` del
        código dice que la 012 pasó su verificación única, que con varios límites legales la
        zona, la cifra y la banda de cada uno son las suyas (corregido, ya no «sigue abierto»),
        la subida de versión de la compilación y las llamadas largas de «Recalcular lo
        obsoleto»; y resume lo corregido tras ver la spec en pantalla (T45 y T46)."""
        text = one_line(CHANGELOG_PATH.read_text(encoding="utf-8"))
        start = text.index("Lo de la spec 012 está comprobado")
        entry = text[start:text.index("### Añadido")]
        for fact in ("verificación única", "varios límites legales", "Recalcular lo obsoleto",
                     "las suyas y no las de la unión"):
            with self.subTest(fact=fact):
                self.assertIn(fact, entry)
        self.assertNotIn("Sigue abierto, para decidir", text)
        self.assertNotIn("la decisión de Samuel sobre varios límites legales", text)
        bullet = text[text.index("**Varios límites legales**"):text.index("**Tras ver la spec")]
        for fact in ("900 m² cada una", "una vez", "versión 1.1", "Recalcular lo obsoleto"):
            with self.subTest(fact=fact):
                self.assertIn(fact, bullet)
        screen = text[text.index("**Tras ver la spec en pantalla**"):text.index(
            "**Cubicación entre superficies**")]
        for fact in ("barra N", "Restricciones", "Cambiar…", "Ir a"):
            with self.subTest(fact=fact):
                self.assertIn(fact, screen)


if __name__ == "__main__":
    unittest.main()
