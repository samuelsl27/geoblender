# SPDX-License-Identifier: GPL-3.0-or-later
"""Una parte de ``python -m unittest discover`` (spec 003, T40; RNF-007-01).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & $PY -B -s -X utf8 tools/unittest_part.py --parte 2/4 discover -v -s tests/unit -t .

Hace lo mismo que ``python -m unittest`` con los argumentos que siguen a ``--parte
i/n`` (que empiezan por ``discover``), pero de las pruebas que descubre solo ejecuta las
de la parte i de n (``gbtools.parts``: módulos enteros). Antes, escribe en la
salida de errores ``PARTE i de n: r de T pruebas``. La salida y los códigos son los de
``unittest``: 0, 1, y 5 si no hay pruebas («NO TESTS RAN»); con opciones no válidas,
2 sin ejecutar nada. Como con ``-m unittest``, ``sys.path`` empieza por la carpeta actual
y no por ``tools/``, y el ``-W`` del intérprete llega a las pruebas.

``tools/check.py`` lo usa para repartir las pruebas unitarias en varios procesos a la
vez; para iterar, ``-m unittest`` (órdenes en ``AGENTS.md``).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ (plan 001 §5.3)

import os  # noqa: E402
import unittest  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import parts  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
DISCOVER = "discover"

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" -B -s -X utf8 tools/unittest_part.py {parts.OPTION} i/n {DISCOVER} [opciones de unittest discover]

  {parts.OPTION} i/n   ejecuta solo la parte i de n de las pruebas que descubre unittest
                (módulos enteros); antes escribe «{parts.LINE_PREFIX} i de n: r de T pruebas»
Lo demás es lo de «python -m unittest {DISCOVER}» (-v, -s, -t, -p…).
Códigos: los de unittest (0, 1, 5 sin pruebas); 2, opciones no válidas."""


class PartLoader(unittest.TestLoader):
    """Un ``TestLoader`` cuyo ``discover`` devuelve solo la parte ``part`` de ``count``
    de lo que descubre, y escribe antes su línea (``parts.line``)."""

    def __init__(self, part: int, count: int) -> None:
        super().__init__()
        self.part = part
        self.count = count

    def discover(
        self, start_dir: str, pattern: str = "test*.py", top_level_dir: str | None = None
    ) -> unittest.TestSuite:
        suite = super().discover(start_dir, pattern, top_level_dir)
        selected, total = parts.select(suite, self.part, self.count)
        print(
            parts.line(self.part, self.count, selected.countTestCases(), total),
            file=sys.stderr,
            flush=True,
        )
        return selected


def _usage_error(message: str) -> int:
    print(f"Error: {message}\n\n{USAGE}", file=sys.stderr)
    return 2


def _same_folder(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(str(b))


def main(argv: Sequence[str] | None = None) -> int:
    """Lee ``--parte i/n discover …`` y ejecuta esa parte con ``unittest.main``, que
    termina el proceso con su código; devuelve 2 si las opciones no son válidas."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != parts.OPTION:
        return _usage_error(f"falta «{parts.OPTION} i/n» al principio")
    if len(args) < 2:
        return _usage_error(f"falta el valor de «{parts.OPTION}»")
    try:
        part, count = parts.parse(args[1])
    except ValueError as exc:
        return _usage_error(str(exc))
    rest = args[2:]
    if not rest or rest[0] != DISCOVER:
        return _usage_error(f"tras «{parts.OPTION} {args[1]}» va «{DISCOVER}»")
    # Como con «python -m unittest»: la carpeta actual, y no la de este guion, al
    # principio de sys.path (gbtools ya está importado).
    if sys.path and _same_folder(sys.path[0], TOOLS_DIR):
        sys.path[0] = os.getcwd()
    program = f"{os.path.basename(sys.executable)} -m unittest"
    unittest.main(module=None, argv=[program, *rest], testLoader=PartLoader(part, count))
    return 0  # unittest.main termina el proceso con su código


if __name__ == "__main__":
    sys.exit(main())
