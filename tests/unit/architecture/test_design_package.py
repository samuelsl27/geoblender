# SPDX-License-Identifier: GPL-3.0-or-later
"""El paquete ``design`` en la arquitectura (spec 013, T02; plan 013 §2, §3 (3 y 4), §5.1 y D-24;
ADR-0004; principios 3 y 4 de la constitución).

``design`` (nivel 8) es dominio puro: Python, ``numpy`` y los paquetes de menor nivel que el plan
permite (``core``, ``jobs`` y ``gis``). **No importa ``reserves``** (nivel 9: la verificación en
m³ por recinto es una orden aparte y la comprobación de congelar va en ``reserves``) **ni ``bl``**,
ni ``adapters`` ni ``workers``, ni una librería externa que no sea ``numpy``. Lo único que necesita
de la 012 fuera de su nivel, el espesor mínimo del informe, lo lee por su clave
(``res.verify.min_thickness_m``) con ``core.params``: la clave sigue declarada en ``reserves``.

Las reglas de dirección (ARQ-07) ya impiden importar un nivel mayor; esta prueba lo dice para
``design`` con nombre y cierra lo que ARQ-07 deja abierto (``adapters.registry`` dentro de una
función, librerías externas distintas de ``numpy``).
"""

from __future__ import annotations

import ast
import sys
import unittest

from tests.support.repo import EXTENSION_DIR

DESIGN_DIR = EXTENSION_DIR / "design"
# Los paquetes de la extensión que ``design`` puede importar (plan 013 §4, ADR-0004).
ALLOWED_PACKAGES = frozenset({"core", "jobs", "gis"})
# Las librerías externas permitidas en el dominio (regla 2 de AGENTS.md: numpy es el de Blender).
ALLOWED_EXTERNAL = frozenset({"numpy"})
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}


def imported_packages(source: str) -> list[tuple[int, str]]:
    """``(línea, paquete)`` de cada import del código de un módulo de ``design``: el paquete de la
    extensión del que viene (``core``, ``reserves``…; ``design`` si es de él mismo) o, si es
    absoluto, el nombre de nivel superior (``numpy``, ``os``…). Cuenta también los imports dentro
    de funciones."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.partition(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                found.append((node.lineno, (node.module or "").partition(".")[0]))
            elif node.level == 1:
                found.append((node.lineno, "design"))
            elif node.module:
                found.append((node.lineno, node.module.partition(".")[0]))
            else:  # ``from .. import core``
                found.extend((node.lineno, alias.name) for alias in node.names)
    return sorted(found)


def problems_of(source: str) -> list[tuple[int, str]]:
    """Lo que ``design`` no puede importar: ``(línea, paquete)`` de cada import que no es de la
    biblioteca estándar, de ``numpy``, del propio ``design`` ni de ``core``, ``jobs`` o ``gis``."""
    allowed = ALLOWED_PACKAGES | ALLOWED_EXTERNAL | STDLIB | {"design"}
    return [(line, name) for line, name in imported_packages(source) if name not in allowed]


class DesignImportsTest(unittest.TestCase):
    def test_design_imports_neither_reserves_nor_bl(self) -> None:
        """Principios 3 y 4, ADR-0004 (RF-013-31, D-19): ningún módulo de ``geoblender/design/``
        importa ``reserves`` ni ``bl`` (ni ``adapters``, ``workers``, ``plans``, ``interop``…) ni
        una librería externa distinta de ``numpy``; solo ``core``, ``jobs`` y ``gis``."""
        paths = sorted(DESIGN_DIR.rglob("*.py"))
        self.assertTrue(paths, "design/ no tiene módulos")
        names = {path.name for path in paths}
        self.assertTrue({"__init__.py", "model.py", "params.py", "messages.py"} <= names)
        found = []
        for path in paths:
            source = path.read_text(encoding="utf-8")
            found.extend(f"{path.relative_to(EXTENSION_DIR).as_posix()}:{line}: importa {name}"
                         for line, name in problems_of(source))
        self.assertEqual(found, [])

    def test_the_check_sees_what_it_forbids(self) -> None:
        """Control positivo: la comprobación ve ``reserves`` y ``bl`` en cualquiera de las formas
        de importarlos (también dentro de una función), una librería externa que no es ``numpy``
        y ``adapters``; no ve lo permitido."""
        bad = (
            "from ..reserves import volumes\n"
            "from .. import bl\n"
            "import scipy.ndimage\n"
            "def f():\n    from ..bl.ops import res\n    from ..adapters import registry\n"
            "import reserves.volumes\n"
        )
        self.assertEqual(problems_of(bad), [(1, "reserves"), (2, "bl"), (3, "scipy"),
                                            (5, "bl"), (6, "adapters"), (7, "reserves")])
        good = (
            "from __future__ import annotations\nimport math\nfrom dataclasses import dataclass\n"
            "import numpy as np\nfrom . import model\nfrom .model import Direction\n"
            "from ..core import units\nfrom ..core.params import ParamDef\n"
            "from ..gis.grid import Grid\nfrom ..jobs import catalog\nfrom .. import gis\n"
        )
        self.assertEqual(problems_of(good), [])


def module_constants(source: str) -> dict[str, object]:
    """Las constantes de nivel de módulo (``NOMBRE = "texto"`` o un número) de un código."""
    found: dict[str, object] = {}
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)):
            found[node.targets[0].id] = node.value.value
    return found


def declared_thickness(source: str) -> dict[str, object]:
    """Lo que ``reserves/provenance.py`` declara del espesor mínimo de la verificación, leído del
    código sin importarlo: la clave (``VERIFY_MIN_THICKNESS``), los primeros argumentos de su
    ``ParamDef`` (clave, tipo de valor, unidad y valor por defecto), su ámbito (``scope=``; sin él,
    el proyecto) y los nombres de ``VERIFY_DEFINITIONS``. ``{}`` si algo no está."""
    constants = module_constants(source)
    definition = members = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        else:
            target = getattr(node, "target", None)
        if not isinstance(target, ast.Name) or getattr(node, "value", None) is None:
            continue
        if target.id == "VERIFY_MIN_THICKNESS_DEF" and isinstance(node.value, ast.Call):
            definition = node.value
        elif target.id == "VERIFY_DEFINITIONS" and isinstance(node.value, ast.Tuple):
            members = [item.id for item in node.value.elts if isinstance(item, ast.Name)]
    if definition is None or members is None or "VERIFY_MIN_THICKNESS" not in constants:
        return {}
    args = [constants.get(arg.id) if isinstance(arg, ast.Name) else getattr(arg, "value", None)
            for arg in definition.args[:4]]
    scope = {kw.arg: getattr(kw.value, "value", None) for kw in definition.keywords}.get("scope")
    return {"key": constants["VERIFY_MIN_THICKNESS"], "definition": args,
            "scope": scope or "project", "members": members}


class MinimumThicknessKeyTest(unittest.TestCase):
    def test_the_key_design_reads_is_still_declared(self) -> None:
        """RF-013-30 (D-24): el espesor mínimo del informe es el de la 012,
        ``res.verify.min_thickness_m``, que ``design`` lee por su clave sin importar
        ``reserves``: sigue declarado en ``reserves`` (``VERIFY_DEFINITIONS``: del proyecto, en
        m, ``float`` y con valor por defecto) y la clave de ``design`` es la misma. Se lee del
        código, sin importar ``reserves`` (cuesta 0,5 s de ``check.py``)."""
        key = "res.verify.min_thickness_m"
        mine = module_constants((DESIGN_DIR / "params.py").read_text(encoding="utf-8"))
        self.assertEqual(mine["VERIFY_MIN_THICKNESS"], key)
        declared = declared_thickness(
            (EXTENSION_DIR / "reserves" / "provenance.py").read_text(encoding="utf-8"))
        self.assertEqual(declared["key"], key)
        self.assertEqual(declared["members"], ["VERIFY_MIN_THICKNESS_DEF"])
        self.assertEqual(declared["scope"], "project")
        declared_key, value_type, unit, default = declared["definition"]
        self.assertEqual((declared_key, value_type, unit), (key, "float", "m"))
        self.assertIsNotNone(default)

    def test_the_reader_sees_a_change(self) -> None:
        """Control positivo: si ``reserves`` cambiara la clave, la unidad o el ámbito, o dejara de
        declararlo, la lectura lo ve (la prueba anterior fallaría)."""
        source = (
            'VERIFY_MIN_THICKNESS = "res.verify.min_thickness_m"\n'
            'VERIFY_MIN_THICKNESS_DEF = ParamDef(VERIFY_MIN_THICKNESS, "float", "m", 0.02, 0.0)\n'
            'VERIFY_DEFINITIONS: tuple[ParamDef, ...] = (VERIFY_MIN_THICKNESS_DEF,)\n'
        )
        self.assertEqual(declared_thickness(source), {
            "key": "res.verify.min_thickness_m", "scope": "project",
            "definition": ["res.verify.min_thickness_m", "float", "m", 0.02],
            "members": ["VERIFY_MIN_THICKNESS_DEF"]})
        versioned = source.replace('0.02, 0.0)', '0.02, 0.0, scope="version")')
        self.assertEqual(declared_thickness(versioned)["scope"], "version")
        renamed = source.replace('"m", 0.02', '"mm", 0.02').replace(
            'VERIFY_MIN_THICKNESS = "res.', 'VERIFY_MIN_THICKNESS = "res.new_')
        self.assertEqual(declared_thickness(renamed)["key"], "res.new_verify.min_thickness_m")
        self.assertEqual(declared_thickness(renamed)["definition"][2], "mm")
        self.assertEqual(declared_thickness("OTRA = 1\n"), {})


if __name__ == "__main__":
    unittest.main()
