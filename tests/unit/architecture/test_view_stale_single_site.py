# SPDX-License-Identifier: GPL-3.0-or-later
"""La marca de vista desfasada (``Scene.geoblender.view_stale``) solo la cambia
``_set_view_stale`` de ``bl/scene/georef.py``, a través de ``mark_stale`` y ``clear_stale``
(spec 009, T43; RF-002-29, RF-010-01): si cambia, pide redibujar todas las ventanas
(``bl.ui.bars.redraw``) y el panel Proyecto, que la lee al dibujarse, la enseña al día.
Cambiarla en otro sitio no redibuja nada: la barra lateral seguiría diciendo lo de antes hasta
que la persona la cierre y la abra (la vuelta en pantalla del 23/10).

En todo ``geoblender/``, con el árbol sintáctico (AST), **escribe** la marca: asignar (también
``+=`` o anotada, y dentro de una tupla) o borrar un atributo ``view_stale``, o
``setattr(<x>, "view_stale", …)``. Leerla (el panel, la marca en vivo) no cuenta.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.rules import pyast  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por la extensión: así
# la analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-extension"

FLAG = "view_stale"
WRITER = "bl/scene/georef.py"  # relativo a la extensión
WRITER_FUNCTION = "_set_view_stale"

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
HEAD = '"""Módulo de prueba."""\n\n'
OFFSET = (SPDX + HEAD).count("\n")


def _writes(tree: ast.AST) -> list[int]:
    """Las líneas de un módulo que escriben la marca (véase el módulo)."""
    lines: set[int] = set()
    for node in pyast.nodes_of(tree, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
        targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
        for target in targets:
            if any(isinstance(item, ast.Attribute) and item.attr == FLAG and
                   isinstance(item.ctx, (ast.Store, ast.Del)) for item in ast.walk(target)):
                lines.add(node.lineno)
    for node in pyast.nodes_of(tree, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "setattr" and \
                len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and \
                node.args[1].value == FLAG:
            lines.add(node.lineno)
    return sorted(lines)


def _allowed(tree: ast.AST) -> range:
    """Las líneas de ``_set_view_stale`` en ``bl/scene/georef.py`` (vacío si no está)."""
    for node in pyast.nodes_of(tree, ast.FunctionDef):
        if node.name == WRITER_FUNCTION and node.end_lineno is not None:
            return range(node.lineno, node.end_lineno + 1)
    return range(0)


def misuses(root: Path) -> list[tuple[str, int]]:
    """Dónde se escribe la marca fuera de ``_set_view_stale`` de ``bl/scene/georef.py``: el
    fichero (relativo a la extensión) y la línea."""
    modules, unparsable = pyast.parse_modules(root, EXT, EXT)
    if unparsable:
        raise AssertionError(f"no se pueden analizar: {unparsable}")
    found: list[tuple[str, int]] = []
    for module in modules:
        rel = module.rel.removeprefix(f"{EXT}/")
        if not any(node.attr == FLAG for node in pyast.nodes_of(module.tree, ast.Attribute)) \
                and not any(node.value == FLAG
                            for node in pyast.nodes_of(module.tree, ast.Constant)):
            continue
        allowed = _allowed(module.tree) if rel == WRITER else range(0)
        found.extend((rel, line) for line in _writes(module.tree) if line not in allowed)
    return sorted(found)


def _found(files: dict[str, str]) -> list[tuple[str, int]]:
    tree = {f"{EXT}/{rel}": SPDX + HEAD + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        return [(rel, line - OFFSET) for rel, line in misuses(root)]


class ViewStaleSingleSiteTest(unittest.TestCase):

    def test_writes_outside_the_single_site(self) -> None:
        """RF-002-29, RF-010-01 (spec 009, T43): cambiar la marca fuera de ``_set_view_stale``
        (asignarla, en una tupla, ``+=``, borrarla, ``setattr``), también en otra función de
        ``bl/scene/georef.py``, falla; dentro, y leerla en cualquier sitio, no."""
        georef = (
            "def _set_view_stale(stale):\n"
            "    for scene in scenes:\n"
            "        scene.geoblender.view_stale = stale\n"
            "\n"
            "def clear_unopened_view():\n"
            "    scene.geoblender.view_stale = False\n"
            "    return any(scene.geoblender.view_stale for scene in scenes)\n"
        )
        other = (
            "item.geoblender.view_stale = False\n"
            "props.view_stale, other = True, 1\n"
            "props.view_stale += 0\n"
            "del props.view_stale\n"
            'setattr(props, "view_stale", True)\n'
            "stale = props.view_stale\n"
        )
        self.assertEqual(
            _found({"bl/scene/georef.py": georef, "bl/scene/views.py": other,
                    "bl/ui/panel.py": "shown = scene.geoblender.view_stale\n"}),
            [("bl/scene/georef.py", 6)] + [("bl/scene/views.py", line) for line in range(1, 6)])

    def test_real_tree(self) -> None:
        """RF-002-29, RF-010-01 (spec 009, T43): en el repositorio real, solo
        ``_set_view_stale`` cambia la marca, y la cambia."""
        self.assertEqual(misuses(ROOT), [])
        tree = pyast.parse_file(ROOT / EXT / WRITER)
        allowed = _allowed(tree)
        self.assertTrue(allowed)
        self.assertTrue(any(line in allowed for line in _writes(tree)))


if __name__ == "__main__":
    unittest.main()
