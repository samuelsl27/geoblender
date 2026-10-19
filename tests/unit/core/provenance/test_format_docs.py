# SPDX-License-Identifier: GPL-3.0-or-later
"""El esquema del proyecto y la API de la procedencia y de las versiones frente a la
documentación (spec 008, T62; ADR-0025, «Obliga a»: ``formato-proyecto.md`` §1 y §3.3–§3.8 y
``modulos/core.md`` con la API; spec 009, T31: el esquema 3, las instantáneas y la API de
``core.versions``).

Como el catálogo de comandos frente a la barra superior (spec 003), el código manda y la
documentación lo describe; estas pruebas avisan de que se separan:

- ``docs/arquitectura/datos/formato-proyecto.md``: el SQL de cada tabla y de cada índice de la
  procedencia (008) y de las versiones (009) está una sola vez en un bloque ``sql`` del
  documento, igual que lo guarda un proyecto nuevo de esta versión (``sqlite_master`` de
  ``core.project.schema.base_image``: las columnas que el esquema 3 añade a las tablas de la 008
  van tras la última) salvo los comentarios, los espacios y «IF NOT EXISTS»; §1 nombra las
  carpetas ``snapshots/``, ``originals/`` y ``orphans/`` (ADR-0025 §8); el ejemplo de
  ``manifest.json`` (§2) lleva el esquema de esta versión; §3.10 nombra cada tipo de evento;
  §4.4, el manifiesto de una instantánea como lo escribe ``core.versions.copy`` (su formato, sus
  secciones, ``referenced``/``ref`` y lo que vale cada clave que no se escribe), y §7, el módulo
  de cada migración;
- ``docs/arquitectura/modulos/core.md``: lo que nombra de los paquetes de la 008, la 009 y la 010
  existe en el código, nombra cada uno de ellos en su API (de ``core.views``, de la 010, cada
  función y cada clase pública de sus cuatro módulos; spec 010, T19; de ``core.versions``, de la
  009, las de :data:`VERSIONS_API`; spec 009, T31) y, en «Datos que posee», cada tabla interna
  del esquema de esta versión.

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
"""

from __future__ import annotations

import json
import re
import sqlite3
import unittest
from contextlib import closing
from types import MappingProxyType

from tests.support import docs
from tests.support.bs_tables import backticked, section
from tests.support.package import import_geoblender

provenance_schema = import_geoblender("core.provenance.schema")
project_schema = import_geoblender("core.project.schema")
migrations = import_geoblender("core.project.migrations")
events = import_geoblender("core.project.events")
originals = import_geoblender("core.inputs.originals")
orphans = import_geoblender("core.datasets.orphans")
versions_schema = import_geoblender("core.versions.schema")
versions_model = import_geoblender("core.versions.model")
versions_copy = import_geoblender("core.versions.copy")

FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
CORE_RELPATH = "docs/arquitectura/modulos/core.md"

# Los paquetes de `core` que crea o amplía la 008 (plan 008 §5.3.1).
PACKAGES_008 = ("units", "hashing", "content", "params", "inputs", "datasets", "provenance")
# El paquete de la 010 (plan 010 §5.3.1, D1: se documenta cuando existe) y sus módulos.
PACKAGES_010 = ("views",)
VIEWS_MODULES = ("state", "inventory", "card", "locate")
# El paquete de la 009 (plan 009 §5.3.1). Sus módulos no declaran ``__all__``: lo que la ficha
# tiene que nombrar de cada uno, sus funciones y sus clases (plan 009 §5.3.1 y lo que añadieron
# sus tareas), sin sus constantes ni sus protocolos.
PACKAGES_009 = ("versions",)
VERSIONS_API: dict[str, tuple[str, ...]] = {
    "schema": ("apply_schema_3", "add_columns", "missing_objects"),
    "model": ("VersionStatus", "RevisionState", "ItemKind", "ItemPart", "ItemState", "Version",
              "Revision", "RevisionItem", "Decision", "VersionError", "version_code",
              "revision_label", "version_locator", "ensure_editable", "compact_manifest",
              "expand_manifest"),
    "read": ("versions", "version", "revisions", "revision", "open_revision", "last_frozen",
             "latest_revisions", "current_version", "default_active", "has_versions",
             "dataset_versions", "dataset_titles", "version_figures", "snapshot_index"),
    "store": ("create_version", "set_status", "set_title", "require_editable", "StatusChange"),
    "freeze": ("freeze_plan", "freeze_steps", "freezing_paths", "FreezePlan", "CopyItem",
               "AcceptItem", "Acceptance", "Blocker", "BlockReason", "FreezeOutcome"),
    "copy": ("copy_steps", "write_manifest", "temporary_path", "acceptance", "rename_snapshot",
             "discard", "SnapshotCopy", "SnapshotFile"),
    "check": ("quick_steps", "check_steps", "full_steps", "record_findings", "conclude",
              "imported_statuses", "SnapshotFinding", "Mismatch", "Problem"),
    "reproduce": ("reproduce_steps", "probable_cause", "detail_text", "ReproduceReport",
                  "ReproduceRequest", "FrozenInput", "ReproducedOutput", "ReproducedResult",
                  "OutputCheck", "FigureCheck", "OperationNote", "Why", "Cause"),
    "decisions": ("record_decision", "decisions", "deciders", "documents"),
}
CHECKED_PACKAGES = (*PACKAGES_008, *PACKAGES_010, *PACKAGES_009, "paths", "userdata")

SQL_FENCE = re.compile(r"^```sql\n(.*?)^```", re.MULTILINE | re.DOTALL)
COMMENT = re.compile(r"--[^\n]*")
CREATE = re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
                    re.IGNORECASE)
CORE_NAME = re.compile(r"^core(?:\.[A-Za-z_]\w*)+")


def normalized(sql: str) -> str:
    """El SQL de una sentencia sin comentarios, sin «IF NOT EXISTS» y con los espacios
    reducidos (ninguno junto a paréntesis y comas)."""
    text = COMMENT.sub(" ", sql)
    text = re.sub(r"\bIF\s+NOT\s+EXISTS\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([(),])\s*", r"\1", text)
    return text.strip().rstrip(";").strip()


def documented_statements(document: str) -> dict[str, list[str]]:
    """Las sentencias ``CREATE TABLE`` y ``CREATE INDEX`` de los bloques ``sql`` del
    documento, normalizadas, por nombre (una lista: un nombre puede salir más de una vez)."""
    found: dict[str, list[str]] = {}
    for block in SQL_FENCE.findall(document):
        for statement in COMMENT.sub(" ", block).split(";"):
            match = CREATE.match(statement)
            if match is not None:
                found.setdefault(match.group(1), []).append(normalized(statement))
    return found


def resolves(dotted: str) -> bool:
    """``core.<paquete>[.<módulo>…].<nombre>[.<atributo>…]`` existe en el código."""
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


@docs.requires_docs
class FormatDocTest(unittest.TestCase):
    """``formato-proyecto.md`` describe el esquema que crea el código."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(FORMAT_RELPATH)

    def test_internal_tables_as_in_a_new_project(self) -> None:
        """RF-008-01, RF-008-02, RF-008-07, RF-008-17, RF-008-18, RF-008-24, RF-008-30,
        RF-008-62 (ADR-0025; plan 008 §5.2.1); RF-009-02, RF-009-04, RF-009-05, RF-009-07,
        RF-009-12, RF-009-13, RF-009-22 (plan 009 §5.2.1 y §5.2.2): cada tabla y cada índice de
        la procedencia y de las versiones está una sola vez en el documento, con el SQL que
        guarda un proyecto nuevo del esquema 3 (las columnas que el 3 añade a ``gb_dataset`` y
        ``gb_operation``, tras su última columna; el índice de nombres vivos, por versión)."""
        documented = documented_statements(self.text)
        tables = set(provenance_schema.INTERNAL_TABLES) | set(versions_schema.INTERNAL_TABLES)
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.deserialize(project_schema.base_image())
            statements = {str(name): str(sql) for name, sql in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') "
                "AND sql IS NOT NULL AND tbl_name IN ({})".format(", ".join("?" * len(tables))),
                sorted(tables))}
        self.assertEqual(len(statements), 29)
        for name, sql in statements.items():
            with self.subTest(name=name):
                self.assertEqual(documented.get(name, []), [normalized(sql)])

    def test_folders_and_schema(self) -> None:
        """RF-008-22, RF-008-53 (ADR-0025 §8; RF-002-20); RF-009-02, RF-009-07: §1 nombra
        ``snapshots/``, ``originals/`` y ``orphans/`` en el árbol de la carpeta y en la tabla de
        quién escribe cada cosa; el ejemplo de ``manifest.json`` lleva el esquema y el mínimo de
        lectura de esta versión, y §7 nombra el módulo de cada migración."""
        tree = section(self.text, "## 1. Estructura de la carpeta")
        for folder in (versions_model.SNAPSHOTS_DIR, originals.ORIGINALS_DIR, orphans.ORPHANS_DIR):
            with self.subTest(folder=folder):
                self.assertRegex(tree, rf"(?m)^  {folder}/ ")
                self.assertRegex(tree, rf"(?m)^\| `{folder}/")
        manifest = section(self.text, "## 2. `manifest.json`")
        self.assertIn(f'"schema_version": {project_schema.SCHEMA_VERSION},', manifest)
        self.assertIn(f'"min_reader_schema": {project_schema.MIN_READER_SCHEMA},', manifest)
        compatibility = section(self.text, "## 7. Compatibilidad y migraciones")
        self.assertTrue(migrations.REGISTRY)
        for migration in migrations.REGISTRY:
            with self.subTest(to=migration.to_version):
                self.assertIn(f"m{migration.to_version:04d}.py", compatibility)

    def test_event_kinds(self) -> None:
        """RF-009-01, RF-009-03, RF-009-06, RF-009-09, RF-009-13, RF-009-22, RF-009-25 (plan 009
        §5.2.6): §3.10 nombra, entre comillas simples, cada tipo de evento que escribe el
        código (``core.project.events.EventKind``), también los de las versiones."""
        events_section = section(self.text, "### 3.10 `gb_event` y `gb_schema_migration`")
        missing = [kind.value for kind in events.EventKind
                   if f"'{kind.value}'" not in events_section]
        self.assertEqual(missing, [])

    def test_snapshot_manifest(self) -> None:
        """RF-009-07, RF-009-09 (plan 009 §5.2.5, D-28; T33): §4.4 dice cómo se reparte una
        instantánea en ficheros (``manifest.json``, el GeoPackage con la etiqueta de la
        revisión, ``rasters/`` y ``meshes/``, y la temporal ``.congelando-``) y describe su
        manifiesto como lo escribe ``core.versions.copy``: ``format`` y ``schema``, cada sección,
        ``referenced`` y ``ref``, y, por sección, lo que vale cada clave que no se escribe
        (``core.versions.model.MANIFEST_ENTRY_DEFAULTS``): ``"clave": valor`` en JSON, o la
        clave sola si lo que vale es nulo."""
        snapshot = section(self.text, "### 4.4 `snapshots/<código>.r<n>/` — instantáneas "
                                      "inmutables")
        for text in (versions_model.SNAPSHOT_MANIFEST, "V10.r2.gpkg", "rasters/", "meshes/",
                     versions_model.FREEZING_MARK, f'"{versions_copy.MANIFEST_FORMAT}"',
                     f'"schema": {versions_copy.MANIFEST_SCHEMA}'):
            with self.subTest(text=text):
                self.assertIn(text, snapshot)
        for key in (versions_model.MANIFEST_REFERENCED, versions_model.MANIFEST_REF,
                    *versions_model.MANIFEST_DEFAULTS):
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", snapshot)
        rows = {cells[0].strip().strip("`"): cells for cells in
                (line.strip().strip("|").split("|") for line in snapshot.splitlines()
                 if line.startswith("| `"))}
        for name, defaults in versions_model.MANIFEST_ENTRY_DEFAULTS.items():
            with self.subTest(section=name):
                self.assertIn(name, rows)
                row = "|".join(rows[name][1:])
                for key, value in defaults.items():
                    shown = (f"`{key}`" if value is None
                             else f"`\"{key}\": {json.dumps(_plain(value), ensure_ascii=False)}`")
                    self.assertIn(shown, row)


def _plain(value: object) -> object:
    """Un valor por defecto del manifiesto como se lee del JSON: ``()`` es ``[]``, y un
    ``MappingProxyType``, un objeto."""
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, MappingProxyType):
        return dict(value)
    return value


@docs.requires_docs
class CoreModuleDocTest(unittest.TestCase):
    """``modulos/core.md`` nombra la API y las tablas que existen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(CORE_RELPATH)

    def test_named_api_exists(self) -> None:
        """RF-008-01, RF-008-07, RF-008-08, RF-008-17, RF-008-18, RF-008-24, RF-008-29,
        RF-008-30 (plan 008 §5.3.1; plan 010 §5.3.1; plan 009 §5.3.1): todo lo que la ficha
        nombra de ``core.units``, ``hashing``, ``content``, ``params``, ``inputs``,
        ``datasets``, ``provenance``, ``views``, ``versions``, ``paths`` y ``userdata`` existe, y
        la API nombra cada paquete de la 008, la 009 y la 010."""
        api = section(self.text, "## API pública")
        named: set[str] = set()
        for token in backticked(self.text):
            match = CORE_NAME.match(token)
            if match is not None and match.group(0).split(".")[1] in CHECKED_PACKAGES:
                named.add(match.group(0))
        self.assertGreater(len(named), 20)
        self.assertEqual(sorted(name for name in named if not resolves(name)), [])
        api_names = {CORE_NAME.match(token).group(0) for token in backticked(api)
                     if CORE_NAME.match(token)}
        for package in (*PACKAGES_008, *PACKAGES_010, *PACKAGES_009):
            with self.subTest(package=package):
                self.assertTrue(any(name == f"core.{package}"
                                    or name.startswith(f"core.{package}.")
                                    for name in api_names))

    def test_views_api_named(self) -> None:
        """RF-010-01, RF-010-02, RF-010-03, RF-010-04, RF-010-05, RF-010-06, RF-010-07,
        RF-010-08 (plan 010 §5.3.1, D1): la API de la ficha nombra, como
        ``core.views.<módulo>.<nombre>``, cada función y cada clase pública (las de ``__all__``
        que no son constantes) de ``core.views.state``, ``inventory``, ``card`` y ``locate``."""
        api = section(self.text, "## API pública")
        api_names = {CORE_NAME.match(token).group(0) for token in backticked(api)
                     if CORE_NAME.match(token)}
        expected: list[str] = []
        for module_name in VIEWS_MODULES:
            module = import_geoblender(f"core.views.{module_name}")
            public = [name for name in module.__all__ if not name.isupper()]
            self.assertTrue(public, f"core.views.{module_name} sin API pública")
            expected.extend(f"core.views.{module_name}.{name}" for name in public)
        self.assertGreater(len(expected), 30)
        self.assertEqual(sorted(name for name in expected if name not in api_names), [])

    def test_versions_api_named(self) -> None:
        """RF-009-01 a RF-009-13, RF-009-19 a RF-009-25, RF-009-29, RF-009-30 (plan 009 §5.3.1):
        la API de la ficha nombra, como ``core.versions.<módulo>.<nombre>``, cada función y cada
        clase de :data:`VERSIONS_API`, que existen en el código y son de su módulo (no lo que
        importa de otro)."""
        api = section(self.text, "## API pública")
        api_names = {CORE_NAME.match(token).group(0) for token in backticked(api)
                     if CORE_NAME.match(token)}
        expected: list[str] = []
        for module_name, names in VERSIONS_API.items():
            module = import_geoblender(f"core.versions.{module_name}")
            for name in names:
                with self.subTest(name=f"{module_name}.{name}"):
                    self.assertEqual(getattr(module, name).__module__, module.__name__)
                expected.append(f"core.versions.{module_name}.{name}")
        self.assertGreater(len(expected), 80)
        self.assertEqual(sorted(name for name in expected if name not in api_names), [])

    def test_owned_tables(self) -> None:
        """RF-008-01, RF-008-07, RF-008-17, RF-008-18, RF-008-24, RF-008-30, RF-008-62:
        «Datos que posee» nombra cada tabla interna del esquema de esta versión (desde la
        spec 009, las cinco de las versiones)."""
        owned = set(backticked(section(self.text, "## Datos que posee")))
        self.assertEqual(len(project_schema.INTERNAL_TABLES), 20)
        self.assertEqual(sorted(set(project_schema.INTERNAL_TABLES) - owned), [])


if __name__ == "__main__":
    unittest.main()
