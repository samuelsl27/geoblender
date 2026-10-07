# SPDX-License-Identifier: GPL-3.0-or-later
"""Una parte de ``python -m unittest discover`` (spec 003, T40; RNF-007-01).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & $PY -B -s -X utf8 tools/unittest_part.py --parte 2/4 [--tiempos F] [--medidas F] discover -v -s tests/unit -t .

Hace lo mismo que ``python -m unittest`` con los argumentos que siguen a ``--parte
i/n`` (y a ``--tiempos`` y ``--medidas``, que empiezan por ``discover``), pero de las
pruebas que descubre solo ejecuta las de la parte i de n (``gbtools.parts``: módulos
enteros). Con ``--tiempos F``, un fichero con la duración de cada módulo, las reparte
por tiempo; sin él, por número de pruebas (spec 004, T39). Con ``--medidas F``, al
terminar escribe en F la duración de cada uno de sus módulos. Antes, escribe en la
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
  & "<Blender>\\5.2\\python\\bin\\python.exe" -B -s -X utf8 tools/unittest_part.py {parts.OPTION} i/n [{parts.TIMES_OPTION} F] [{parts.MEASURES_OPTION} F] {DISCOVER} [opciones de unittest discover]

  {parts.OPTION} i/n     ejecuta solo la parte i de n de las pruebas que descubre unittest
                  (módulos enteros); antes escribe «{parts.LINE_PREFIX} i de n: r de T pruebas»
  {parts.TIMES_OPTION} F    reparte por la duración de cada módulo del fichero F (sin él, o
                  sin medidas, por número de pruebas)
  {parts.MEASURES_OPTION} F    al terminar, escribe en F la duración de cada módulo de la parte
Lo demás es lo de «python -m unittest {DISCOVER}» (-v, -s, -t, -p…).
Códigos: los de unittest (0, 1, 5 sin pruebas); 2, opciones no válidas."""


class PartLoader(unittest.TestLoader):
    """Un ``TestLoader`` cuyo ``discover`` devuelve solo la parte ``part`` de ``count``
    de lo que descubre (por los tiempos de ``times`` si se da), y escribe antes su línea
    (``parts.line``); con ``measures``, una suite que al terminar escribe allí la
    duración de cada módulo (``parts.measured``)."""

    def __init__(
        self, part: int, count: int, times: Path | None = None, measures: Path | None = None
    ) -> None:
        super().__init__()
        self.part = part
        self.count = count
        self.times = times
        self.measures = measures

    def discover(
        self, start_dir: str, pattern: str = "test*.py", top_level_dir: str | None = None
    ) -> unittest.TestSuite:
        suite = super().discover(start_dir, pattern, top_level_dir)
        times = parts.read_times(self.times) if self.times is not None else None
        selected, total = parts.select(suite, self.part, self.count, times)
        print(
            parts.line(self.part, self.count, selected.countTestCases(), total),
            file=sys.stderr,
            flush=True,
        )
        if self.measures is not None:
            return parts.measured(selected, self.part, self.count, self.measures)
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
    files: dict[str, Path | None] = {parts.TIMES_OPTION: None, parts.MEASURES_OPTION: None}
    while rest and rest[0] in files:
        if len(rest) < 2 or not rest[1] or rest[1] == DISCOVER:
            return _usage_error(f"falta el fichero de «{rest[0]}»")
        files[rest[0]] = Path(rest[1])
        rest = rest[2:]
    if not rest or rest[0] != DISCOVER:
        return _usage_error(f"tras «{parts.OPTION} {args[1]}» va «{DISCOVER}»")
    # Como con «python -m unittest»: la carpeta actual, y no la de este guion, al
    # principio de sys.path (gbtools ya está importado).
    if sys.path and _same_folder(sys.path[0], TOOLS_DIR):
        sys.path[0] = os.getcwd()
    program = f"{os.path.basename(sys.executable)} -m unittest"
    loader = PartLoader(
        part, count, files[parts.TIMES_OPTION], files[parts.MEASURES_OPTION]
    )
    unittest.main(module=None, argv=[program, *rest], testLoader=loader)
    return 0  # unittest.main termina el proceso con su código


if __name__ == "__main__":
    sys.exit(main())
