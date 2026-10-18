# SPDX-License-Identifier: GPL-3.0-or-later
"""El esquema 2 y la API de la procedencia frente a la documentación (spec 008, T62;
ADR-0025, «Obliga a»: ``formato-proyecto.md`` §1 y §3.3–§3.8 con el esquema 2 y las
carpetas, y ``modulos/core.md`` con la API).

Como el catálogo de comandos frente a la barra superior (spec 003), el código manda y la
documentación lo describe; estas pruebas avisan de que se separan:

- ``docs/arquitectura/datos/formato-proyecto.md``: el SQL de cada tabla y de cada índice de la
  procedencia (``core.provenance.schema``) está una sola vez en un bloque ``sql`` del
  documento, igual que en el código salvo los comentarios, los espacios y «IF NOT EXISTS»; §1
  nombra las carpetas ``originals/`` y ``orphans/`` (ADR-0025 §8); el ejemplo de
  ``manifest.json`` (§2) lleva el esquema de esta versión, y §7, el módulo de cada migración;
- ``docs/arquitectura/modulos/core.md``: lo que nombra de los paquetes de la 008 y de la 010
  existe en el código, nombra cada uno de ellos en su API (de ``core.views``, de la 010, cada
  función y cada clase pública de sus cuatro módulos; spec 010, T19) y, en «Datos que posee»,
  cada tabla interna del esquema de esta versión.

Sin la carpeta de la documentación, se omiten (recurso ``docs``).
"""

from __future__ import annotations

import re
import unittest

from tests.support import docs
from tests.support.bs_tables import backticked, section
from tests.support.package import import_geoblender

provenance_schema = import_geoblender("core.provenance.schema")
project_schema = import_geoblender("core.project.schema")
migrations = import_geoblender("core.project.migrations")
originals = import_geoblender("core.inputs.originals")
orphans = import_geoblender("core.datasets.orphans")

FORMAT_RELPATH = "docs/arquitectura/datos/formato-proyecto.md"
CORE_RELPATH = "docs/arquitectura/modulos/core.md"

# Los paquetes de `core` que crea o amplía la 008 (plan 008 §5.3.1).
PACKAGES_008 = ("units", "hashing", "content", "params", "inputs", "datasets", "provenance")
# El paquete de la 010 (plan 010 §5.3.1, D1: se documenta cuando existe) y sus módulos.
PACKAGES_010 = ("views",)
VIEWS_MODULES = ("state", "inventory", "card", "locate")
CHECKED_PACKAGES = (*PACKAGES_008, *PACKAGES_010, "paths")

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

    def test_provenance_tables_as_in_the_code(self) -> None:
        """RF-008-01, RF-008-02, RF-008-07, RF-008-17, RF-008-18, RF-008-24, RF-008-30,
        RF-008-62 (ADR-0025; plan 008 §5.2.1): cada tabla y cada índice de la procedencia
        está una sola vez en el documento, con el SQL del código."""
        documented = documented_statements(self.text)
        statements = {**provenance_schema.TABLES, **provenance_schema.INDEXES}
        self.assertEqual(len(statements), 19)
        for name, sql in statements.items():
            with self.subTest(name=name):
                self.assertEqual(documented.get(name, []), [normalized(sql)])

    def test_folders_and_schema(self) -> None:
        """RF-008-22, RF-008-53 (ADR-0025 §8; RF-002-20): §1 nombra ``originals/`` y
        ``orphans/`` en el árbol de la carpeta y en la tabla de quién escribe cada cosa; el
        ejemplo de ``manifest.json`` lleva el esquema y el mínimo de lectura de esta versión, y
        §7 nombra el módulo de cada migración."""
        tree = section(self.text, "## 1. Estructura de la carpeta")
        for folder in (originals.ORIGINALS_DIR, orphans.ORPHANS_DIR):
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


@docs.requires_docs
class CoreModuleDocTest(unittest.TestCase):
    """``modulos/core.md`` nombra la API y las tablas que existen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(CORE_RELPATH)

    def test_named_api_exists(self) -> None:
        """RF-008-01, RF-008-07, RF-008-08, RF-008-17, RF-008-18, RF-008-24, RF-008-29,
        RF-008-30 (plan 008 §5.3.1; plan 010 §5.3.1): todo lo que la ficha nombra de
        ``core.units``, ``hashing``, ``content``, ``params``, ``inputs``, ``datasets``,
        ``provenance``, ``views`` y ``paths`` existe, y la API nombra cada paquete de la 008 y
        de la 010."""
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
        for package in (*PACKAGES_008, *PACKAGES_010):
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

    def test_owned_tables(self) -> None:
        """RF-008-01, RF-008-07, RF-008-17, RF-008-18, RF-008-24, RF-008-30, RF-008-62:
        «Datos que posee» nombra cada tabla interna del esquema de esta versión (desde la
        spec 009, las cinco de las versiones)."""
        owned = set(backticked(section(self.text, "## Datos que posee")))
        self.assertEqual(len(project_schema.INTERNAL_TABLES), 20)
        self.assertEqual(sorted(set(project_schema.INTERNAL_TABLES) - owned), [])


if __name__ == "__main__":
    unittest.main()
