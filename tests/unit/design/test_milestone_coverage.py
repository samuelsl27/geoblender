# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué deja la 015 en el «verde» y qué en el paso «hito» (spec 015, T48; RNF-015-07; plan 015 §7.4).

La comprobación de cada tarea (``tools/check.py``) tiene que terminar en ≤ 48 s (RNF-001-01), y las
pruebas de la 015 que repiten un escenario con proyecto por variante pesaban ≈ 11 s de más: pasaron a
``milestone_*.py``, que el «verde» no descubre y ejecuta el paso «hito» de ``--completo`` (la
publicación lo pide siempre). Estas pruebas guardan el trato: **cada requisito tiene al menos una
prueba en el «verde»** y lo que se movió **no se repite** (una prueba copiada en vez de movida
correría dos veces).
"""

import ast
import fnmatch
import re
import unittest
from pathlib import Path

from tests.support.repo import ROOT

REQUIREMENTS = range(1, 30)
"""Los RF-015-01 a RF-015-29 de la spec (RF-015-26 y RF-015-28 solo tienen pruebas de Blender)."""
VERDE_FOLDERS = ("tests/unit", "tests/blender", "tests/referencia")
"""Donde el «verde» busca sus pruebas (con ``test*.py``)."""
CITATION = re.compile(r"\bRF-015-(\d\d)\b")
MILESTONE_CITATION = re.compile(r"\bRF-01[56]-(\d\d)\b")
"""Lo que cita una prueba de hito: un requisito de la 015 o de la 016 (spec 016, T10: los ``milestone_*.py`` de la 016
usan este mismo paso; la cobertura del «verde» de la 015, arriba, no cambia)."""


def _files(pattern: str) -> list[Path]:
    found: list[Path] = []
    for folder in VERDE_FOLDERS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "__pycache__" not in path.parts and fnmatch.fnmatch(path.name, pattern):
                found.append(path)
    return found


def _tests(path: Path) -> dict[str, str]:
    """``{"Clase.prueba": docstring}`` de los métodos ``test…`` de las clases del fichero."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith(
                "test"
            ):
                found[f"{node.name}.{item.name}"] = ast.get_docstring(item) or ""
    return found


class MilestoneCoverageTest(unittest.TestCase):
    def test_every_requirement_has_a_test_in_the_green(self) -> None:
        """RNF-015-07, RF-015-01 a RF-015-29: cada requisito de la 015 lo cita el docstring de al
        menos una prueba que descubre el «verde» (``test*.py`` de ``tests/unit``, ``tests/blender``
        y ``tests/referencia``): lo que se mueve a ``milestone_*.py`` no deja un requisito sin
        prueba rápida."""
        cited: set[int] = set()
        for path in _files("test*.py"):
            text = path.read_text(encoding="utf-8")
            if "RF-015-" not in text:
                continue
            for docstring in _tests(path).values():
                cited.update(int(number) for number in CITATION.findall(docstring))
        missing = [f"RF-015-{number:02d}" for number in REQUIREMENTS if number not in cited]
        self.assertEqual(missing, [], "requisitos sin ninguna prueba en el «verde»")

    def test_what_was_moved_is_not_repeated(self) -> None:
        """RNF-015-07: una ``milestone_X.py`` y su ``test_X.py`` no comparten ninguna prueba (la
        misma clase y el mismo método): se mueve, no se copia, y nada corre dos veces."""
        milestones = _files("milestone_*.py")
        self.assertTrue(milestones, "no hay ninguna prueba de hito")
        for path in milestones:
            sibling = path.with_name("test_" + path.name.removeprefix("milestone_"))
            if not sibling.is_file():
                continue
            with self.subTest(hito=path.name):
                repeated = sorted(set(_tests(path)) & set(_tests(sibling)))
                self.assertEqual(repeated, [], f"también en {sibling.name}")

    def test_every_milestone_is_a_real_test_module(self) -> None:
        """RNF-015-07: cada ``milestone_*.py`` tiene pruebas y cita algún requisito de la 015 o de la
        016 (si no, el paso «hito» no le serviría a ninguno)."""
        for path in _files("milestone_*.py"):
            with self.subTest(hito=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                found = _tests(path)
                self.assertTrue(found, "sin pruebas")
                cited = set(MILESTONE_CITATION.findall(ast.get_docstring(tree) or ""))
                for docstring in found.values():
                    cited.update(MILESTONE_CITATION.findall(docstring))
                self.assertTrue(cited, "no cita ningún RF-015 ni RF-016")


if __name__ == "__main__":
    unittest.main()
