# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación de la documentación de Geoblender (plan 007 §5.4.3; ADR-0023;
RF-007-11 a RF-007-13 y RF-007-28).

Se ejecuta con el Python de Blender (solo usa la biblioteca estándar)::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" -B tools/check_docs.py [CARPETA]

1. La carpeta (RF-007-12): ``CARPETA``; si no se da, la de ``GEOBLENDER_DOCS_DIR``; y
   si tampoco, la carpeta madre del repositorio de código cuando tiene
   ``docs/constitution.md`` (``gbtools.repo.find_docs``). Sin carpeta, o si no existe,
   no se puede leer o no tiene ``docs/constitution.md``: lo dice y sale con 2
   (RF-007-13).
2. Las reglas de la documentación (``gbtools.rules.DOCS_FAMILIES``: ADR-01, AGT-01,
   AGT-02, NOM-03 y TXT-01 a 03) sobre sus ficheros, sin ``.git/``, ``Documentacion/``,
   ``Promts/``, la carpeta ``Geoblender/`` del código (con cualquier mayúscula) ni lo que
   ignora su ``.gitignore`` (RF-007-11); y REP-03 (RF-007-28): ningún remoto en
   ``.git/config`` (leído como texto, sin lanzar git) y ``Geoblender/`` ignorada en su
   ``.gitignore``.
3. No crea, cambia ni borra nada en la carpeta: una foto (rutas, tamaños y
   ``mtime_ns``, sin ``.git/`` ni la carpeta del código) antes y otra después; si
   difieren, «DOCUMENTACIÓN MODIFICADA» con la lista y código 1.
4. Imprime cada incumplimiento como ``fichero:línea: [REGLA] mensaje`` y
   ``RESULTADO: DOCUMENTACIÓN CORRECTA (n ficheros, s)`` o ``RESULTADO: DOCUMENTACIÓN
   CON INCUMPLIMIENTOS (n)``. Nunca «VERDE»: ese es el resultado del código
   (``tools/check.py``).

Desde la carpeta del proyecto, tras el corte: ``& $PY -B Geoblender\\tools\\check_docs.py``
(la carpeta madre). En el repositorio único (fases 0 a 2 de la spec 007), con la carpeta:
``& $PY -B tools\\check_docs.py .``.

Códigos de salida: 0 sin incumplimientos; 1 algún incumplimiento, o la documentación
cambió durante la comprobación; 2 uso, sin carpeta, carpeta inexistente, ilegible o sin
``docs/constitution.md``, o un ``.gitignore`` que no se puede aplicar.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en las carpetas de datos

import os  # noqa: E402
import time  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools.findings import format_findings  # noqa: E402
from gbtools.ignore import UnsupportedPattern  # noqa: E402
from gbtools.layout import CODE_DIR_IN_DOCS, DOCS_EXCLUDED, ENV_DOCS_DIR  # noqa: E402
from gbtools.repo import (  # noqa: E402
    DocsProblem,
    docs_root,
    find_docs,
    iter_repo_files,
    repo_root,
    snapshot,
    snapshot_changes,
)
from gbtools.rules import run_docs  # noqa: E402

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
# Lo que la foto no recorre: lo cambia git, y el código tiene su propia comprobación.
SNAPSHOT_SKIP: tuple[str, ...] = (".git", CODE_DIR_IN_DOCS)

USAGE = """Uso (con el Python de Blender):
  & "<Blender>\\5.2\\python\\bin\\python.exe" -B tools/check_docs.py [CARPETA]

  CARPETA      la documentación (por defecto, GEOBLENDER_DOCS_DIR o la carpeta madre
               del repositorio de código, si tiene docs/constitution.md)
  --ayuda, -h  muestra esta ayuda

Códigos: 0 correcta, 1 incumplimientos, 2 sin documentación u opción no válida."""

NO_DOCS = (
    "no hay documentación: pase su carpeta como argumento, defina "
    f"{ENV_DOCS_DIR} o ponga el repositorio de código dentro de ella (la carpeta "
    "madre, con docs/constitution.md)"
)


class UsageError(Exception):
    """Una opción o un número de argumentos que la orden no admite."""


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def parse_args(args: Sequence[str]) -> tuple[str | None, bool]:
    """La carpeta (o ``None``) y si se pidió la ayuda; :class:`UsageError` si no vale."""
    folder: str | None = None
    show_help = False
    for arg in args:
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
        elif arg.startswith("-"):
            raise UsageError(f"opción desconocida «{arg}»")
        elif folder is not None:
            raise UsageError("se comprueba una sola carpeta")
        else:
            folder = arg
    return folder, show_help


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> int:
    """Comprueba la documentación y devuelve el código de salida.

    ``environ`` y ``root`` (la raíz del repositorio de código, cuya carpeta madre es la
    documentación por defecto) solo los cambian las pruebas.
    """
    started = time.perf_counter()
    environ = os.environ if environ is None else environ
    try:
        argument, show_help = parse_args(list(sys.argv[1:] if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return EXIT_USAGE
    if show_help:
        print(__doc__)
        print(USAGE)
        return EXIT_OK
    if root is None:
        try:
            root = repo_root(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
    source = (
        "el argumento"
        if argument
        else ENV_DOCS_DIR
        if environ.get(ENV_DOCS_DIR)
        else "la carpeta madre del repositorio de código"
    )
    found = find_docs(root, environ, argument)
    if found is None:
        print(f"ERROR: {NO_DOCS}", file=sys.stderr)
        return EXIT_USAGE
    try:
        folder = docs_root(found)
    except DocsProblem as exc:
        print(f"ERROR: {exc} (carpeta tomada de {source})", file=sys.stderr)
        return EXIT_USAGE

    print(f"Geoblender · comprobación de la documentación · {folder}")
    before = snapshot(folder, SNAPSHOT_SKIP)
    try:
        findings = run_docs(folder)
        count = sum(1 for _path in iter_repo_files(folder, DOCS_EXCLUDED))
    except UnsupportedPattern as exc:
        print(
            f"ERROR: no se puede aplicar el .gitignore de «{folder}»: {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    changes = snapshot_changes(before, snapshot(folder, SNAPSHOT_SKIP))
    seconds = _seconds(time.perf_counter() - started)
    if findings:
        print(format_findings(findings))
    if changes:
        listed = "\n".join(f"  {change}" for change in changes)
        print(
            f"DOCUMENTACIÓN MODIFICADA durante la comprobación ({len(changes)}): la "
            f"comprobación no escribe en la documentación.\n{listed}"
        )
    if findings or changes:
        total = len(findings) + len(changes)
        print(f"RESULTADO: DOCUMENTACIÓN CON INCUMPLIMIENTOS ({total})")
        return EXIT_FINDINGS
    print(f"RESULTADO: DOCUMENTACIÓN CORRECTA ({count} ficheros, {seconds} s)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
