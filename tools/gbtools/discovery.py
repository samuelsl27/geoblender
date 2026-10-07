# SPDX-License-Identifier: GPL-3.0-or-later
"""Ficheros de prueba en disco frente a módulos que ``unittest`` cargó (RF-001-06;
convergencia de la spec 001, T35).

``unittest discover`` deja sin cargar, sin avisar, un fichero de pruebas en una carpeta
sin ``__init__.py`` (desde Python 3.11) o con un nombre que no es un módulo válido: sus
pruebas no se ejecutan y la orden termina con 0. ``tools/check.py`` (sobre la salida de
``unittest -v``) y ``tools/run_blender_tests.py`` (sobre la suite descubierta) comparan
lo que hay en disco con lo que se cargó y fallan si falta algo. Solo biblioteca estándar.

También fija la línea final del lanzador (``launcher_end_line``, T37): la última que
escribe ``run_blender_tests.py`` al terminar, con el número de pruebas y su código;
``check.py`` la exige cuando Blender sale con 0, porque un ``os._exit(0)`` a mitad de
una prueba saldría con 0 sin ella.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

UNITTEST_PATTERN = "test*.py"  # el patrón por defecto de ``unittest discover``
CACHE_FOLDER = "__pycache__"

# Cabecera de una prueba en la salida de ``unittest -v``: «test_x (paquete.módulo.Clase.
# test_x)», o «setUpClass (paquete.módulo.Clase)» y «setUpModule (paquete.módulo)».
TEST_HEAD = re.compile(r"^(?P<name>[A-Za-z_]\w*) \((?P<where>[\w.]+)\)", re.MULTILINE)

HINT = (
    "¿falta «__init__.py» en su carpeta (TST-01), su nombre no es un módulo válido o no "
    "tiene pruebas?"
)

# Una prueba que devuelve algo en lugar de ejecutar su cuerpo (``async def`` en un
# ``TestCase`` que no es ``IsolatedAsyncioTestCase``, o con ``yield``): ``unittest`` de
# Python 3.13 solo avisa con este ``DeprecationWarning`` y la da por buena. Las órdenes de
# pruebas lo convierten en error (convergencia de la spec 001, T54).
RETURN_VALUE_WARNING = "It is deprecated to return a value"
UNITTEST_WARNINGS = f"error:{RETURN_VALUE_WARNING}:DeprecationWarning"  # para «-W»

# Una prueba roja marcada con ``expectedFailure``: ``unittest`` la cuenta como «expected
# failures=n» dentro de «OK (…)» y sale con 0. No es verde: ``check.py``, el lanzador y
# el banco la ponen en fallo, y la regla TST-07 la señala en ``tests/`` (convergencia de
# la spec 001, T59).
EXPECTED_FAILURES_MARK = "expected failures="
EXPECTED_FAILURES_HINT = (
    "una prueba marcada con expectedFailure falló y unittest la da por buena; una prueba "
    "roja no es verde (TST-07, RF-001-06): quite expectedFailure y arregle la prueba, o "
    "pruebe el error esperado con assertRaises"
)

LAUNCHER_END_PREFIX = "FIN DEL LANZADOR"
LAUNCHER_END = re.compile(
    rf"^{LAUNCHER_END_PREFIX}: (\d+) pruebas?, código (\d+)\s*$", re.MULTILINE
)


def launcher_end_line(count: int, code: int) -> str:
    """Última línea del lanzador: ``FIN DEL LANZADOR: 12 pruebas, código 0``."""
    noun = "prueba" if count == 1 else "pruebas"
    return f"{LAUNCHER_END_PREFIX}: {count} {noun}, código {code}"


def expected_modules(folder: Path, pattern: str, top_level: Path) -> dict[str, str]:
    """``{módulo: ruta}`` de los ficheros de prueba de ``folder`` que ``unittest
    discover`` debería cargar: los ``.py`` cuyo nombre casa ``pattern`` como en
    ``unittest`` (``fnmatch``), a cualquier profundidad y sin ``__pycache__``. El módulo
    y la ruta (con «/») son relativos a ``top_level``. Un nombre que no es un módulo
    válido también cuenta: ``unittest`` lo saltaría sin avisar."""
    found: dict[str, str] = {}
    if not folder.is_dir():
        return found
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(name for name in dirs if name != CACHE_FOLDER)
        for name in sorted(files):
            if not name.lower().endswith(".py") or not fnmatch.fnmatch(name, pattern):
                continue
            rel = (Path(current) / name).relative_to(top_level).as_posix()
            found[rel[: -len(".py")].replace("/", ".")] = rel
    return found


def loaded_in_output(text: str) -> set[str]:
    """Lo que nombran las cabeceras de las pruebas en la salida de ``unittest -v``."""
    return {match.group("where") for match in TEST_HEAD.finditer(text)}


def is_loaded(module: str, names: set[str]) -> bool:
    """Si ``names`` (lo que nombra la salida) nombra el módulo ``module`` o algo de
    dentro de él."""
    prefix = module + "."
    return module in names or any(name.startswith(prefix) for name in names)


def missing_modules(expected: Mapping[str, str], loaded: Iterable[str]) -> list[str]:
    """Rutas de los ficheros de ``expected`` cuyo módulo no se cargó: ningún nombre de
    ``loaded`` es el módulo ni algo de dentro de él. Ordenadas."""
    names = set(loaded)
    return sorted(rel for module, rel in expected.items() if not is_loaded(module, names))
