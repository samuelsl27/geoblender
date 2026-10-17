# SPDX-License-Identifier: GPL-3.0-or-later
"""Las cifras de cada objeto de la vista son una copia para mostrar (spec 010, T16; RF-010-08;
plan 010 §5.2, A8 y D-17; principio 2): ``Object.geoblender.figures`` solo lo escribe
``bl/scene/views.py`` (al cargar y al refrescar, regeneradas desde el proyecto) y solo lo lee
``bl/ui`` (para mostrarlas); ningún cálculo las lee. Las cifras se leen del proyecto, con su
tipo y su procedencia: una propiedad de la escena no es su fuente.

En todo ``geoblender/``, con el árbol sintáctico (AST):

- **escribe** las cifras de un objeto: llamar a ``add``, ``clear``, ``remove``, ``move`` o
  ``foreach_set`` de un atributo ``figures`` (lo que tiene una colección de Blender: una tupla
  o un conjunto del dominio no se llaman así como atributo), y asignar o borrar ``figures`` (o
  uno de sus elementos) del grupo del objeto, o ``setattr(<grupo>, "figures", …)``;
- **lee** las cifras de un objeto cualquier otro uso de ``<grupo>.figures`` o
  ``getattr(<grupo>, "figures")``;

donde el **grupo del objeto** (``Object.geoblender``) es un atributo con el nombre de
``OBJECT_PROPERTY`` de ``bl/props/core.py`` (``obj.<grupo>``), ``getattr(obj,
OBJECT_PROPERTY)`` (o con ese nombre como literal) o un nombre al que el módulo le asigna uno
de esos (``props = getattr(obj, OBJECT_PROPERTY)``).

Límite declarado: no ve el grupo cuando llega con otro nombre como argumento de una función
(``_put_figures(props, …)``: lo que escribe sí, por sus métodos) ni dentro de una comprensión;
lo cubren las pruebas de Blender (``test_views_state``, ``test_views_panels``) y la revisión del
código.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.rules import pyast  # noqa: E402

# Va en la misma parte que las demás pruebas que pasan las reglas por la extensión: así
# la analizan una sola vez (spec 006, T47; gbtools.parts.affinity_of).
PART_AFFINITY = "reglas-extension"

FIGURES = "figures"
WRITER = "bl/scene/views.py"  # relativo a la extensión
READERS = "bl/ui/"
PROPS_MODULE = "bl/props/core.py"
GROUP_CONSTANT = "OBJECT_PROPERTY"
WRITE_METHODS = frozenset({"add", "clear", "remove", "move", "foreach_set"})

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
HEAD = '"""Módulo de prueba."""\n\n'
OFFSET = (SPDX + HEAD).count("\n")


def object_group(root: Path) -> str:
    """El nombre del grupo de Geoblender de cada objeto: el valor de ``OBJECT_PROPERTY`` en
    ``bl/props/core.py`` (así esta prueba no lo escribe a mano)."""
    tree = pyast.parse_file(root / EXT / PROPS_MODULE)
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and any(
                isinstance(target, ast.Name) and target.id == GROUP_CONSTANT
                for target in node.targets):
            return str(node.value.value)
    raise AssertionError(f"{PROPS_MODULE} no define {GROUP_CONSTANT}")


@dataclass(frozen=True)
class Use:
    """Un uso de las cifras de un objeto: dónde (relativo a la extensión) y si las escribe."""

    rel: str
    line: int
    write: bool


def _is_group(node: ast.AST, group: str, names: frozenset[str]) -> bool:
    """Si ``node`` es el grupo de Geoblender de un objeto (véase el módulo)."""
    if isinstance(node, ast.Attribute):
        return node.attr == group
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
            node.func.id == "getattr" and len(node.args) >= 2:
        key = node.args[1]
        return (isinstance(key, ast.Name) and key.id == GROUP_CONSTANT) or (
            isinstance(key, ast.Constant) and key.value == group)
    return isinstance(node, ast.Name) and node.id in names


def _group_names(tree: ast.AST, group: str) -> frozenset[str]:
    """Los nombres a los que el módulo asigna el grupo de un objeto (también de otro nombre
    que ya lo es)."""
    names: frozenset[str] = frozenset()
    while True:
        found = set(names)
        for node in pyast.nodes_of(tree, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            value = node.value
            if value is None or not _is_group(value, group, names):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found.update(target.id for target in targets if isinstance(target, ast.Name))
        if found == names:
            return names
        names = frozenset(found)


def _figures_of(node: ast.AST, group: str, names: frozenset[str]) -> bool:
    """Si ``node`` es ``<grupo>.figures`` o uno de sus elementos (``<grupo>.figures[0]``)."""
    if isinstance(node, ast.Subscript):
        node = node.value
    return isinstance(node, ast.Attribute) and node.attr == FIGURES and \
        _is_group(node.value, group, names)


def _named_call(node: ast.Call, function: str) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == function and \
        len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and \
        node.args[1].value == FIGURES


def module_uses(tree: ast.AST, rel: str, group: str) -> list[Use]:
    """Los usos de las cifras de un objeto en un módulo (``rel``, relativo a la extensión)."""
    if not any(node.attr == FIGURES for node in pyast.nodes_of(tree, ast.Attribute)) and \
            not any(isinstance(node.value, str) and node.value == FIGURES
                    for node in pyast.nodes_of(tree, ast.Constant)):
        return []
    names = _group_names(tree, group)
    uses: list[Use] = []
    seen: set[int] = set()  # los ``<x>.figures`` ya contados como escritura
    for node in pyast.nodes_of(tree, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS and \
                isinstance(func.value, ast.Attribute) and func.value.attr == FIGURES:
            uses.append(Use(rel, node.lineno, True))
            seen.add(id(func.value))
        elif _named_call(node, "setattr") and _is_group(node.args[0], group, names):
            uses.append(Use(rel, node.lineno, True))
        elif _named_call(node, "getattr") and _is_group(node.args[0], group, names):
            uses.append(Use(rel, node.lineno, False))
    for node in pyast.nodes_of(tree, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
        targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
        for target in targets:
            if _figures_of(target, group, names):
                uses.append(Use(rel, node.lineno, True))
                seen.add(id(target.value if isinstance(target, ast.Subscript) else target))
    for node in pyast.nodes_of(tree, ast.Attribute):
        if id(node) not in seen and _figures_of(node, group, names):
            uses.append(Use(rel, node.lineno, False))
    return sorted(set(uses), key=lambda use: (use.rel, use.line, use.write))


def figure_uses(root: Path, group: str) -> list[Use]:
    """Todos los usos de las cifras de un objeto en ``geoblender/`` bajo ``root``."""
    modules, unparsable = pyast.parse_modules(root, EXT, EXT)
    if unparsable:
        raise AssertionError(f"no se pueden analizar: {unparsable}")
    found: list[Use] = []
    for module in modules:
        found.extend(module_uses(module.tree, module.rel.removeprefix(f"{EXT}/"), group))
    return sorted(found, key=lambda use: (use.rel, use.line, use.write))


def misuses(uses: list[Use]) -> list[tuple[str, int, str]]:
    """Los usos que no son de su sitio: una escritura fuera de ``bl/scene/views.py`` y una
    lectura fuera de ``bl/ui`` (la de ``bl/scene/views.py`` también: solo las escribe)."""
    return [(use.rel, use.line, "escribe" if use.write else "lee") for use in uses
            if (use.rel != WRITER if use.write else not use.rel.startswith(READERS))]


def _found(files: dict[str, str], group: str) -> list[tuple[str, int, str]]:
    tree = {f"{EXT}/{rel}": SPDX + HEAD + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        found = misuses(figure_uses(root, group))
    return [(rel, line - OFFSET, what) for rel, line, what in found]


class ViewFiguresTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.group = object_group(ROOT)

    def test_writes_outside_the_view_module(self) -> None:
        """RF-010-08 (plan D-17): escribir las cifras de un objeto (sus métodos, asignarlas,
        borrarlas, ``setattr``) fuera de ``bl/scene/views.py``, también desde ``bl/ui``,
        falla."""
        g = self.group
        text = (
            "props = getattr(obj, OBJECT_PROPERTY)\n"
            "props.figures.clear()\n"
            f"item = obj.{g}.figures.add()\n"
            f'setattr(obj.{g}, "figures", ())\n'
            f'del getattr(obj, "{g}").figures[0]\n'
            "x.figures.remove(item)\n"
            f"obj.{g}.figures = []\n"
        )
        found = _found({"bl/ops/cifras.py": text,
                        "bl/ui/panel.py": f"obj.{g}.figures.move(0, 1)\n"}, g)
        self.assertEqual(found, [("bl/ops/cifras.py", line, "escribe") for line in range(2, 8)]
                         + [("bl/ui/panel.py", 1, "escribe")])

    def test_reads_outside_the_interface(self) -> None:
        """RF-010-08 (plan D-17), principio 2: leer las cifras de un objeto fuera de ``bl/ui``
        (un cálculo del dominio, una orden, el propio ``bl/scene/views.py``) falla, con el grupo
        por su atributo, por ``getattr`` o por un nombre que lo guarda."""
        g = self.group
        found = _found({
            "core/cubicar.py": f"total = sum(f.value_text for f in obj.{g}.figures)\n",
            "bl/ops/cifras.py": (
                "props = getattr(obj, OBJECT_PROPERTY)\n"
                "for figure in props.figures:\n"
                "    pass\n"
                f'n = len(getattr(obj.{g}, "figures"))\n'
                "alias = props\n"
                "first = alias.figures[0]\n"
            ),
            "bl/scene/views.py": f"if obj.{g}.figures:\n    pass\n",
        }, g)
        self.assertEqual(found, [("bl/ops/cifras.py", 2, "lee"), ("bl/ops/cifras.py", 4, "lee"),
                                 ("bl/ops/cifras.py", 6, "lee"), ("bl/scene/views.py", 1, "lee"),
                                 ("core/cubicar.py", 1, "lee")])

    def test_allowed(self) -> None:
        """RF-010-08: ``bl/scene/views.py`` las escribe y ``bl/ui`` las lee; las cifras del
        dominio (``DatasetFigures.figures``, ``ItemCard.figures``, un conjunto ``figures``, una
        caché ``_figures``) no son las de un objeto."""
        g = self.group
        found = _found({
            "bl/scene/views.py": (
                "props = getattr(obj, OBJECT_PROPERTY)\n"
                "props.figures.clear()\n"
                "item = props.figures.add()\n"
                "for found in card.dataset_figures(project, uids):\n"
                "    texts = found.figures\n"
            ),
            "bl/ui/panel.py": (
                f"for figure in obj.{g}.figures:\n"
                "    layout.label(text=figure.value_text)\n"
                "n = len(getattr(obj, OBJECT_PROPERTY).figures)\n"
            ),
            "core/views/card.py": (
                "figures = by_operation.get(record.operation_uid, ())\n"
                "shown = [figure.uid for figure in found.figures]\n"
                "self.figures = figures\n"
                "figures.add(current)\n"
                "self._figures.clear()\n"
            ),
        }, g)
        self.assertEqual(found, [])

    def test_real_tree(self) -> None:
        """RF-010-08 (plan D-17): en el código real, solo ``bl/scene/views.py`` escribe las
        cifras de un objeto (la regla lo ve: al cargar y al refrescar) y nadie fuera de
        ``bl/ui`` las lee."""
        uses = figure_uses(ROOT, self.group)
        self.assertEqual(misuses(uses), [])
        self.assertTrue([use for use in uses if use.write and use.rel == WRITER])


if __name__ == "__main__":
    unittest.main()
