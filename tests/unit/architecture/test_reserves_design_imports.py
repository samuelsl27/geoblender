# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que ``reserves`` importa de ``design`` (spec 017, T18b; HU-017-3; RF-012-22, RF-012-24; plan 017 §5.1, §5.4 A12, §6 («La verificación lee la accesibilidad por su
papel y por final»), §7.1 y §8; DIFF-012 de la 017, §3 y §4; principios 3 y 4 de la constitución; ADR-0004).

``reserves`` (nivel 9) puede importar de ``design`` (nivel 8: ARQ-07 ya lo permite). Lo que esta prueba cierra es **cuánto**: la verificación de la 012 lee lo que las
operaciones de las pistas dejan **por su papel** (``design.provenance``: las constantes de los papeles), la lectura de lo guardado (``design.access_store``,
``design.stockpile_store``) y nada de las entidades ni de las pistas:

- **Permitido:** ``design.access_store``, ``design.stockpile_store``, ``design.provenance`` (con cualquiera de sus nombres: las constantes) y, de ``design.entities``,
  **solo** ``chain_tail_surfaces`` (la 015, T32: la última superficie de cada cadena, para ``freeze_findings``; la lista blanca de lo que ya importaba ``reserves``).
- **Prohibido:** ``design.road_*`` (las pistas y su cálculo), cualquier otro nombre de ``design.entities`` y cualquier otro módulo de ``design``; también ``import design`` entero
  (no se sabría qué usa) y el import absoluto. La verificación **no** acopla las entidades (el texto aprobado de la T18, «``reserves`` no importa ``design.entities``»,
  se afinó el 21/11/2026 con esta lista: ``compliance_store`` ya importaba ``chain_tail_surfaces`` desde la 015).

El otro sentido —``design`` **sigue sin** importar ``reserves``, ``bl``, ``adapters``, ``workers`` ni una librería externa que no sea ``numpy``— lo comprueban
``tests/unit/architecture/test_design_package.py`` (con nombre, sobre todos sus módulos, también los de las pistas) y ``test_dependency_direction.py`` (ARQ-02 y ARQ-07); aquí
se vuelve a pasar la primera sobre los módulos que la 017 añade o toca, para que esta spec no dependa de que otra prueba siga viva.
"""

from __future__ import annotations

import ast
import unittest

from tests.support.repo import EXTENSION_DIR
from tests.unit.architecture.test_design_package import problems_of

RESERVES_DIR = EXTENSION_DIR / "reserves"
DESIGN_DIR = EXTENSION_DIR / "design"
ALLOWED_MODULES = frozenset({"access_store", "stockpile_store", "provenance"})
"""Los módulos de ``design`` que ``reserves`` puede importar enteros."""
ALLOWED_NAMES = {"entities": frozenset({"chain_tail_surfaces"})}
"""De los demás módulos de ``design``, solo estos nombres."""


def design_imports(source: str) -> list[tuple[int, str, str]]:
    """``(línea, módulo de design, nombre)`` de cada import de ``design`` en el código de un módulo de ``reserves``, también dentro de funciones: el módulo (``''`` si el
    import es del paquete ``design`` entero) y el nombre que importa (``''`` si importa el módulo: ``from ..design import access_store``)."""
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head, _dot, rest = alias.name.partition(".")
                if head == "design":
                    found.append((node.lineno, rest.partition(".")[0], ""))
        elif isinstance(node, ast.ImportFrom) and node.level in (0, 2):  # desde reserves, ``..`` es la extensión; ``.`` es reserves
            head, _dot, inner = (node.module or "").partition(".")
            if head == "design" and inner:  # ``from ..design.entities import chain_tail_surfaces``
                found.extend((node.lineno, inner.partition(".")[0], alias.name) for alias in node.names)
            elif head == "design":  # ``from ..design import access_store`` (el nombre es un módulo, o algo del ``__init__``)
                found.extend((node.lineno, alias.name, "") for alias in node.names)
            elif not head and node.level == 2:  # ``from .. import design``
                found.extend((node.lineno, "", "") for alias in node.names if alias.name == "design")
    return sorted(found)


def forbidden(source: str) -> list[tuple[int, str]]:
    """Lo que ``reserves`` no puede importar de ``design``: ``(línea, qué)`` de cada import que no es de la lista blanca."""
    found: list[tuple[int, str]] = []
    for line, module, name in design_imports(source):
        if not module:
            found.append((line, "el paquete design entero"))
        elif name:
            if name not in ALLOWED_NAMES.get(module, frozenset()) and module not in ALLOWED_MODULES:
                found.append((line, f"design.{module}.{name}"))
        elif module not in ALLOWED_MODULES:
            found.append((line, f"design.{module}"))
    return found


class ReservesImportsTest(unittest.TestCase):
    def test_reserves_imports_only_what_the_verification_reads_by_role(self) -> None:
        """RF-012-22, RF-012-24, DIFF-012 §4: ningún módulo de ``geoblender/reserves/`` importa ``design.road_*``, otro nombre de ``design.entities`` que
        ``chain_tail_surfaces`` ni otro módulo de ``design`` que ``access_store``, ``stockpile_store`` y ``provenance``."""
        paths = sorted(RESERVES_DIR.rglob("*.py"))
        names = {path.name for path in paths}
        self.assertTrue({"__init__.py", "compliance.py", "compliance_store.py"} <= names)
        found = []
        for path in paths:
            found.extend(f"{path.relative_to(EXTENSION_DIR).as_posix()}:{line}: importa {what}" for line, what in forbidden(path.read_text(encoding="utf-8")))
        self.assertEqual(found, [])

    def test_the_algorithm_does_not_import_design_at_all(self) -> None:
        """RF-012-22 (A12: «el algoritmo no importa ``design``»): ``reserves/compliance.py`` recibe el conjunto de las zonas comunicadas y no sabe de dónde sale; solo
        ``compliance_store.py``, que toca el proyecto, lee la accesibilidad."""
        source = (RESERVES_DIR / "compliance.py").read_text(encoding="utf-8")
        self.assertEqual(design_imports(source), [])

    def test_the_verification_does_read_the_access_by_its_role(self) -> None:
        """RF-012-24: ``compliance_store`` importa de verdad la lectura de la accesibilidad (``design.access_store``) y las constantes de sus papeles
        (``design.provenance``); si dejara de hacerlo, la prueba de lo prohibido no protegería nada."""
        source = (RESERVES_DIR / "compliance_store.py").read_text(encoding="utf-8")
        found = {(module, name) for _line, module, name in design_imports(source)}
        self.assertIn(("access_store", ""), found)
        self.assertTrue([item for item in found if item[0] == "provenance"])
        self.assertEqual({name for module, name in found if module == "entities"}, {"chain_tail_surfaces"})

    def test_the_check_sees_what_it_forbids(self) -> None:
        """Control positivo: la comprobación ve las pistas (por módulo o por nombre), las entidades salvo ``chain_tail_surfaces``, otro módulo de ``design``, el paquete
        entero y el import absoluto, también dentro de una función; no ve lo permitido ni lo que no es de ``design``."""
        bad = (
            "from ..design import road_model\n"  # 1: las pistas
            "from ..design.road_store import prepare_road\n"  # 2
            "from ..design.entities import chain_tail_surfaces, registry\n"  # 3: solo ``registry`` sobra
            "from ..design import entities\n"  # 4: el módulo entero de las entidades
            "from ..design.platform import work_window\n"  # 5: otro módulo de design
            "from .. import design\n"  # 6: el paquete entero
            "import design.road_axis\n"  # 7: el import absoluto
            "def f():\n"
            "    from ..design.road_net import build_net\n"  # 9: dentro de una función
        )
        self.assertEqual([line for line, _what in forbidden(bad)], [1, 2, 3, 4, 5, 6, 7, 9])
        self.assertEqual(forbidden(bad)[2], (3, "design.entities.registry"))
        self.assertEqual(forbidden(bad)[5], (6, "el paquete design entero"))
        good = (
            "from ..design import access_store, stockpile_store\n"
            "from ..design.entities import chain_tail_surfaces\n"
            "from ..design.provenance import ROAD_ACCESS_ZONES_ROLE, STOCKPILE_BASE_ROLE\n"
            "from ..design.access_store import read_zone_table\n"
            "from ..core import units\nfrom ..gis import store\nfrom . import compliance\nimport json\n"
            "def f():\n"
            "    from ..design import access_store\n"
        )
        self.assertEqual(forbidden(good), [])
        self.assertEqual(len(design_imports(good)), 7)

    def test_design_still_imports_neither_reserves_nor_bl_nor_external_libraries(self) -> None:
        """Principios 3 y 4, ADR-0004 (RF-017-24, RF-017-25): los módulos de ``design`` que la 017 añade o toca (las pistas, la accesibilidad, las entidades, los papeles y los
        mensajes) no importan ``reserves`` ni ``bl`` (ni ``adapters``, ``workers``…) ni una librería externa que no sea ``numpy``; es la comprobación de
        ``test_design_package`` sobre ellos."""
        paths = sorted({*DESIGN_DIR.glob("road_*.py"), *(DESIGN_DIR / name for name in ("access_store.py", "entities.py", "entity_store.py", "provenance.py", "params.py",
                                                                                        "messages.py", "steps.py", "store.py", "reproduce.py"))})
        self.assertGreaterEqual(len(paths), 10)
        found = []
        for path in paths:
            self.assertTrue(path.is_file(), path.name)
            found.extend(f"{path.relative_to(EXTENSION_DIR).as_posix()}:{line}: importa {name}" for line, name in problems_of(path.read_text(encoding="utf-8")))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
