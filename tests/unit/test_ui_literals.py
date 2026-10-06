# SPDX-License-Identifier: GPL-3.0-or-later
"""Ningún texto visible de la interfaz se escribe fuera del catálogo (spec 003, T29;
RNF-003-08; RF-003-20; II §2.7; plan 003 §5.3, contrato 4).

Análisis del árbol sintáctico de ``geoblender/bl/`` (sin importar ``bpy``): un **literal**
de texto (constante o *f-string*) en

- ``text=`` de cualquier llamada (``layout.label``, ``operator``, ``menu``, ``prop``…),
- ``bl_label`` y ``bl_description`` de una clase,
- el mensaje de ``report()`` y de ``poll_message_set()``,
- el nombre y la descripción de un elemento de un enumerado (``items`` de
  ``EnumProperty``, en línea o en una constante ``*_ITEMS`` del módulo: se ven en el panel
  F9, en el mapa de teclado y en las descripciones emergentes),

- y, en ``bl/ops/`` (spec 003, T33), el nombre y la descripción de las propiedades de los
  operadores (``name=`` y ``description=`` de ``*Property``: ``bl.ui.registry`` las traduce
  al cambiar de idioma y se ven en el panel F9 y en el mapa de teclado),

tiene que ser un ``msgid`` del catálogo: una etiqueta o descripción del catálogo de
comandos (``core.catalog``) o un texto de ``core/i18n/messages.toml``, que es lo que tiene
traducción (los vacíos no cuentan). Una *f-string* nunca lo es. ``tests/unit/core/i18n/
test_ui_texts.py`` (spec 002) es más estricta con ``text=``, ``report`` y
``poll_message_set`` (ningún literal: siempre ``tr(…)``), y comprueba los ``msgid`` de
``tr``.

Control positivo: el detector ve un literal sembrado a propósito en cada uno de esos sitios
y no da por malo un ``msgid``.
"""

import ast
import unittest
from collections.abc import Iterator

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")

BL_DIR = EXTENSION_DIR / "bl"
CLASS_TEXTS = ("bl_label", "bl_description")
MESSAGE_ARGUMENT = {"report": 1, "poll_message_set": 0}  # posición del mensaje
ITEMS_SUFFIX = "_ITEMS"


def known_msgids() -> frozenset[str]:
    """Los ``msgid`` con traducción: los del catálogo de comandos y los de
    ``messages.toml``."""
    return frozenset(catalog.load().msgids()) | frozenset(i18n.load_messages())


def _function_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _text_of(node: ast.AST) -> str | None:
    """El texto de un literal (``None`` si no es un literal de texto; una *f-string*, su
    código fuente aproximado, que nunca es un ``msgid``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "f" + ast.unparse(node)
    return None


def _enum_items(node: ast.AST) -> Iterator[tuple[int, str]]:
    """(línea, texto) de los nombres y descripciones de una lista de elementos de un
    enumerado: tuplas de 3 o más con el identificador primero."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return
    for element in node.elts:
        if not isinstance(element, ast.Tuple) or len(element.elts) < 3:
            continue
        for part in element.elts[1:3]:
            value = _text_of(part)
            if value is not None:
                yield part.lineno, value


def literals(tree: ast.AST) -> Iterator[tuple[int, str, str]]:
    """(línea, sitio, texto) de cada literal de texto en un sitio visible."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id in CLASS_TEXTS:
                        value = _text_of(statement.value)
                        if value is not None:
                            yield statement.lineno, target.id, value
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name.endswith(ITEMS_SUFFIX) for name in names):
                for line, value in _enum_items(node.value):
                    yield line, "items", value
        elif isinstance(node, ast.Call):
            name = _function_name(node)
            for keyword in node.keywords:
                if keyword.arg == "text":
                    value = _text_of(keyword.value)
                    if value is not None:
                        yield node.lineno, f"{name}(text=…)", value
                elif keyword.arg == "items" and name == "EnumProperty":
                    for line, value in _enum_items(keyword.value):
                        yield line, "items", value
            position = MESSAGE_ARGUMENT.get(name)
            if position is not None and len(node.args) > position:
                value = _text_of(node.args[position])
                if value is not None:
                    yield node.lineno, name, value


def property_texts(tree: ast.AST) -> Iterator[tuple[int, str, str]]:
    """(línea, sitio, texto) del nombre y la descripción literales de cada propiedad de
    ``bpy.props`` (``EnumProperty(name="Mode", …)``)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _function_name(node).endswith("Property"):
            continue
        for keyword in node.keywords:
            if keyword.arg in ("name", "description"):
                value = _text_of(keyword.value)
                if value is not None:
                    yield node.lineno, f"{_function_name(node)}({keyword.arg}=…)", value


def outside_catalog(tree: ast.AST, msgids: frozenset[str]) -> list[tuple[int, str, str]]:
    """Los literales visibles que no son un ``msgid`` con traducción (los vacíos, sí)."""
    return [(line, where, value) for line, where, value in literals(tree)
            if value and value not in msgids]


def _bl_trees() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(BL_DIR.rglob("*.py")):
        rel = path.relative_to(EXTENSION_DIR).as_posix()
        yield rel, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class UiLiteralsTest(unittest.TestCase):
    def test_bl_has_no_text_outside_the_catalog(self) -> None:
        """RNF-003-08: en ``bl/`` todo literal visible es un ``msgid`` del catálogo."""
        msgids = known_msgids()
        found = [f"{rel}:{line}: {where} «{value}»"
                 for rel, tree in _bl_trees()
                 for line, where, value in outside_catalog(tree, msgids)]
        self.assertEqual(found, [])
        count = sum(1 for _rel, tree in _bl_trees() for _ in literals(tree))
        self.assertGreater(count, 40, "los bl_label de los operadores reales se revisan")

    def test_operator_properties_in_the_catalog(self) -> None:
        """RNF-003-08, RF-003-21 (T33): el nombre y la descripción de cada propiedad de un
        operador de ``bl/ops/`` es un ``msgid`` con traducción; control positivo con una
        sembrada."""
        msgids = known_msgids()
        found = [f"{rel}:{line}: {where} «{value}»"
                 for rel, tree in _bl_trees() if rel.startswith("bl/ops/")
                 for line, where, value in property_texts(tree)
                 if value and value not in msgids]
        self.assertEqual(found, [])
        seeded = ast.parse("x = FloatProperty(name='Semiancho raro', description='Half width')")
        self.assertEqual([value for _line, _where, value in property_texts(seeded)
                          if value not in msgids], ["Semiancho raro"])

    def test_detector_sees_seeded_literals(self) -> None:
        """Control positivo: un literal sembrado en cada sitio se detecta; un ``msgid``, un
        texto vacío, una variable o ``tr(…)``, no."""
        source = (
            "class GEOBLENDER_OT_ui_prueba(bpy.types.Operator):\n"
            "    bl_label = 'Hola'\n"
            "    bl_description = 'Switch this window between the Geoblender interface and "
            "the Blender one'\n"
            "layout.label(text='Adiós')\n"
            "layout.label(text='')\n"
            "layout.label(text=tr('Project'))\n"
            "self.report({'INFO'}, f'Hecho {n}')\n"
            "cls.poll_message_set('Sin proyecto todavía')\n"
            "cls.poll_message_set(mensaje)\n"
            "VIEW_ITEMS = [('PLAN', 'Plan', ''), ('RARA', 'Vista rara', '')]\n"
            "prop = EnumProperty(items=[('A', 'Opción A', 'Ayuda rara')])\n"
            "row.operator('geoblender.ui_toggle_mode', text='Switch Geoblender ⇄ Blender')\n"
        )
        found = sorted(outside_catalog(ast.parse(source), known_msgids()))
        self.assertEqual([(line, where) for line, where, _value in found],
                         [(2, "bl_label"), (4, "label(text=…)"), (7, "report"),
                          (8, "poll_message_set"), (10, "items"), (11, "items"),
                          (11, "items")])


if __name__ == "__main__":
    unittest.main()
