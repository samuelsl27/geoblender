# SPDX-License-Identifier: GPL-3.0-or-later
"""Los textos de la interfaz pasan por el catálogo de idioma (spec 002, T28; constitución,
principio 10; iconos-e-idioma.md §2.7).

En ``geoblender/bl/`` (árbol sintáctico, sin importar ``bpy``):

- cada ``tr("…")`` usa un ``msgid`` de ``messages.toml`` y le pasa exactamente sus
  marcadores;
- ningún texto visible se escribe a mano: ni ``text=`` con un literal no vacío, ni el
  mensaje de ``report``, ``poll_message_set`` o ``notify`` como literal o *f-string*
  (lo que viene de ``core`` ya está en español con objeto, campo y valor, y llega como
  variable).
"""

import ast
import unittest
from collections.abc import Iterator
from pathlib import Path

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

i18n = import_geoblender("core.i18n")

BL_DIR = EXTENSION_DIR / "bl"
# Llamadas cuyo mensaje (posición del argumento) no puede ser un literal.
MESSAGE_ARGUMENT = {"report": 1, "poll_message_set": 0, "notify": 0}


def _function_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_literal_text(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(node.value)


def _calls(tree: ast.AST) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def literal_texts(tree: ast.AST) -> list[tuple[int, str]]:
    """(línea, llamada) de cada texto visible escrito a mano."""
    found: list[tuple[int, str]] = []
    for call in _calls(tree):
        name = _function_name(call)
        for keyword in call.keywords:
            if keyword.arg == "text" and _is_literal_text(keyword.value):
                found.append((call.lineno, f"{name}(text=…)"))
        position = MESSAGE_ARGUMENT.get(name)
        if position is not None and len(call.args) > position:
            if _is_literal_text(call.args[position]):
                found.append((call.lineno, name))
    return found


def tr_calls(tree: ast.AST) -> list[tuple[int, str | None, set[str]]]:
    """(línea, msgid literal o ``None``, nombres de los valores) de cada ``tr(…)``."""
    found = []
    for call in _calls(tree):
        if _function_name(call) != "tr":
            continue
        first = call.args[0] if call.args else None
        msgid = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
        found.append((call.lineno, msgid, {k.arg for k in call.keywords if k.arg}))
    return found


def _bl_trees() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(BL_DIR.rglob("*.py")):
        rel = path.relative_to(EXTENSION_DIR).as_posix()
        yield rel, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class UiTextsTest(unittest.TestCase):
    def test_tr_msgids_in_catalog(self) -> None:
        """Principio 10, RF-002-34: cada ``tr`` de ``bl/`` usa un ``msgid`` literal del
        catálogo, con traducción, y le pasa exactamente sus marcadores."""
        table = i18n.load_messages()
        problems: list[str] = []
        count = 0
        for rel, tree in _bl_trees():
            for line, msgid, names in tr_calls(tree):
                count += 1
                where = f"{rel}:{line}"
                if msgid is None:
                    problems.append(f"{where}: el msgid no es un literal")
                elif msgid not in table:
                    problems.append(f"{where}: «{msgid}» no está en messages.toml")
                elif names != i18n.placeholders(msgid):
                    problems.append(f"{where}: «{msgid}» con {sorted(names)}")
        self.assertEqual(problems, [])
        self.assertGreater(count, 30, "la interfaz de la spec 002 usa el catálogo")

    def test_no_handwritten_texts(self) -> None:
        """Principio 10: en ``bl/`` ningún ``text=``, ``report``, ``poll_message_set`` ni
        ``notify`` lleva un texto escrito a mano."""
        found = [
            f"{rel}:{line}: {call}"
            for rel, tree in _bl_trees()
            for line, call in literal_texts(tree)
        ]
        self.assertEqual(found, [])

    def test_detector_sees_literals(self) -> None:
        """Control positivo: el detector ve un ``text=`` literal, una *f-string* en
        ``report`` y un literal en ``poll_message_set`` y ``notify``; no un ``text=`` vacío,
        una variable ni ``tr(…)``."""
        source = (
            "layout.label(text='Hola')\n"
            "layout.label(text='')\n"
            "layout.label(text=tr('Project'))\n"
            "self.report({'INFO'}, f'Hecho {x}')\n"
            "self.report({'INFO'}, exc.message)\n"
            "cls.poll_message_set('No hay proyecto')\n"
            "project_session.notify(mensaje)\n"
            "notify('Aviso')\n"
        )
        found = literal_texts(ast.parse(source))
        self.assertEqual([line for line, _ in found], [1, 4, 6, 8])
        calls = tr_calls(ast.parse("tr('Name: {name}', name=x)\ntr(variable)\n"))
        self.assertEqual(calls, [(1, "Name: {name}", {"name"}), (2, None, set())])


if __name__ == "__main__":
    unittest.main()
