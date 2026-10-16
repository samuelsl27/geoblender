# SPDX-License-Identifier: GPL-3.0-or-later
"""Arnés de los bancos privados de Geoblender (plan 001 §5.4.15; RF-001-10, RF-001-11,
RNF-001-05).

Se ejecuta con el Python de Blender desde la raíz del repositorio, sin opciones, y solo
si se pide: ``tools/check.py --banco`` (paso «banco»). Los datos de los bancos nunca
entran en el repositorio: cada banco llega por su variable de entorno (``BANKS``), y sus
comparaciones viven en ``tests/banco/<banco>/``. Una spec que añade un banco añade su
fila a ``BANKS`` y su carpeta de comparaciones, sin otra herramienta.

Por banco:

1. Sin su variable, o si no apunta a una carpeta legible: ``OMITIDO: <banco>: <motivo>``.
2. Foto de la carpeta (rutas, tamaños y ``mtime_ns``, con ``os.scandir``, sin abrir
   ningún fichero).
3. Comparaciones: ``unittest discover`` de ``tests/banco/<banco>/`` en este proceso, con
   la variable disponible; sin ninguna, «sin comparaciones registradas». Una comparación
   roja marcada con ``expectedFailure`` («expected failures») es un fallo (T59).
4. Foto de nuevo: cualquier diferencia es un fallo, con la lista de cambios (el banco
   es de solo lectura, RNF-001-05).

Nunca imprime ni guarda datos del banco, ni su ruta: solo los nombres de las
comparaciones, sus resultados y, si la carpeta cambió, las rutas relativas cambiadas.

Códigos de salida: 0 correcto (o sin comparaciones; también si se omite algún banco y
otro pasa); 1 una comparación falló o la carpeta de un banco cambió; 2 error de uso;
3 omitido (ningún banco tiene su variable definida y una carpeta legible).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import os  # noqa: E402
import re  # noqa: E402
import unittest  # noqa: E402
import warnings  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import discovery  # noqa: E402

# La foto (rutas, tamaños y mtime_ns, sin abrir ficheros) y sus diferencias son las de
# gbtools.repo, que también usa tools/check.py con el repositorio.
from gbtools.repo import snapshot  # noqa: E402
from gbtools.repo import snapshot_changes as changes  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
TESTS_RELPATH = Path("tests") / "banco"

# Banco → variable de entorno con su carpeta (solo lectura): Silvestre (spec 001, U4) y la
# base de sondeos de RecMin (spec 005, D-3, DP-65).
BANKS: Mapping[str, str] = {
    "silvestre": "GEOBLENDER_SILVESTRE_DIR",
    "recmin": "GEOBLENDER_RECMIN_BANK_DIR",
}

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_OMITTED = 3


def _omission(name: str, variable: str, environ: Mapping[str, str]) -> str | None:
    """Motivo para omitir el banco, o ``None`` si su carpeta está disponible."""
    value = environ.get(variable, "").strip()
    if not value:
        return (
            f"la variable {variable} no está definida; defínala con la carpeta del banco "
            "(solo lectura) para contrastar las cifras"
        )
    folder = Path(value)
    try:
        readable = folder.is_dir() and os.access(folder, os.R_OK)
        if readable:
            with os.scandir(folder) as listing:
                next(listing, None)
    except OSError:
        readable = False
    if not readable:
        return f"{variable} no apunta a una carpeta legible; corrija la variable"
    return None


def _run_comparisons(folder: Path, top_level: Path) -> unittest.TestResult | None:
    """Ejecuta las comparaciones de ``folder``; ``None`` si no hay ninguna.

    Los módulos de las comparaciones que se cargan (los del paquete de ``folder``) y la
    entrada que ``discover`` añade a ``sys.path`` se retiran al terminar, para que otra
    ejecución no reutilice comparaciones de otra carpeta con el mismo nombre.
    """
    package = Path(folder).resolve().relative_to(Path(top_level).resolve()).parts[0]
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    try:
        loader = unittest.TestLoader()
        suite = loader.discover(
            str(folder), pattern="test*.py", top_level_dir=str(top_level)
        )
        if suite.countTestCases() == 0:
            return None
        with warnings.catch_warnings():
            # Una comparación que devuelve algo (async def, yield) no se ejecuta: error
            # (convergencia de la spec 001, T54).
            warnings.filterwarnings(
                "error",
                message=re.escape(discovery.RETURN_VALUE_WARNING),
                category=DeprecationWarning,
            )
            return unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - saved_modules:
            if name == package or name.startswith(package + "."):
                del sys.modules[name]


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def run_bank(name: str, folder: Path, comparisons: Path, top_level: Path) -> bool:
    """Ejecuta las comparaciones de un banco disponible; verdadero si todo va bien."""
    before = snapshot(folder)
    if comparisons.is_dir():
        result = _run_comparisons(comparisons, top_level)
    else:
        result = None
    after = snapshot(folder)
    ok = True
    if result is None:
        summary = "sin comparaciones registradas"
    else:
        count = result.testsRun
        # Una comparación roja marcada con expectedFailure no es correcta (T59).
        problems = (
            len(result.failures)
            + len(result.errors)
            + len(result.expectedFailures)
            + len(result.unexpectedSuccesses)
        )
        if result.wasSuccessful() and not result.expectedFailures:
            summary = _plural(count, "comparación correcta", "comparaciones correctas")
        else:
            ok = False
            summary = f"FALLO: {problems} de {_plural(count, 'comparación', 'comparaciones')}"
    differences = changes(before, after)
    if differences:
        ok = False
        print(
            f"Banco «{name}»: {summary}; FALLO: la carpeta del banco ha cambiado y es de "
            "solo lectura (RNF-001-05):"
        )
        for line in differences:
            print(f"  {line}")
    else:
        print(f"Banco «{name}»: {summary}; la carpeta no ha cambiado")
    return ok


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    banks: Mapping[str, str] = BANKS,
    tests_dir: Path | None = None,
) -> int:
    """Ejecuta los bancos y devuelve el código de salida.

    ``root`` (raíz del repositorio), ``banks`` y ``tests_dir`` (carpeta con una
    subcarpeta de comparaciones por banco) solo los cambian las pruebas.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"], ["--ayuda"]):
        print(__doc__)
        return EXIT_OK
    if args:
        print(
            f"Opción no admitida: {' '.join(args)}. Uso: tools/bench_silvestre.py (sin "
            "opciones; lo lanza tools/check.py --banco)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    root = ROOT if root is None else Path(root)
    tests_dir = root / TESTS_RELPATH if tests_dir is None else Path(tests_dir)
    if tests_dir.resolve().is_relative_to(root.resolve()):
        top_level = root
    else:
        top_level = tests_dir.parent
    available = 0
    ok = True
    for name, variable in banks.items():
        reason = _omission(name, variable, os.environ)
        if reason is not None:
            print(f"OMITIDO: {name}: {reason}")
            continue
        available += 1
        folder = Path(os.environ[variable].strip())
        ok = run_bank(name, folder, tests_dir / name, top_level) and ok
    if available == 0:
        print("Bancos: omitidos (ninguno tiene su variable definida y una carpeta legible)")
        return EXIT_OMITTED
    print("Bancos: correcto" if ok else "Bancos: NO VERDE")
    return EXIT_OK if ok else EXIT_FAILED


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())
