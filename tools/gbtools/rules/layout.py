# SPDX-License-Identifier: GPL-3.0-or-later
"""REP: el árbol de la raíz del repositorio de código (spec 007; plan 007 §5.4.2).

- REP-01 (RF-007-01): cada entrada de la raíz con algún fichero del repositorio
  comprobado (``iter_repo_files``: sin ``.git/`` y con el ``.gitignore`` aplicado) está,
  con su mayúscula exacta, en ``gbtools.layout.CODE_ROOT_ENTRIES``. Así no entran en el
  código ``docs/``, ``specs/`` ni nada de la documentación, que vive en su propio
  repositorio; tampoco un *worktree* dentro del repositorio (``.claude/worktrees/``).
- REP-02 (RF-007-08): la raíz contiene la carpeta de la extensión con su nombre exacto,
  mayúsculas incluidas (``gbtools.layout.EXTENSION_DIR``, mirado con ``os.listdir``),
  con el manifiesto y al menos un ``.py`` (en cualquier nivel). En Windows una
  mayúscula distinta no se nota al abrir los ficheros, pero las rutas relativas de las
  reglas salen con la del disco y las reglas de ámbito «extensión» se quedarían sin
  ficheros y en verde.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..findings import Finding
from ..layout import CODE_ROOT_ENTRIES, EXTENSION_DIR, MANIFEST_RELPATH
from ..repo import iter_repo_files, relpath

RULE_ROOT_ENTRIES = "REP-01"
RULE_EXTENSION_DIR = "REP-02"


def check_root_entries(root: Path) -> list[Finding]:
    """REP-01: las entradas de la raíz que no son del repositorio de código, una vez
    cada una (con la mayúscula del disco)."""
    entries = sorted(
        {relpath(root, path).split("/", 1)[0] for path in iter_repo_files(root)}
        - CODE_ROOT_ENTRIES
    )
    allowed = ", ".join(sorted(CODE_ROOT_ENTRIES, key=str.casefold))
    return [
        Finding(
            entry,
            0,
            RULE_ROOT_ENTRIES,
            f"«{entry}» no es una entrada del repositorio de código: en su raíz solo van "
            f"{allowed}, con esa mayúscula. La documentación (docs/, specs/…) vive en su "
            "propio repositorio; quite la entrada, ignórela en .gitignore si es local o "
            "pida un cambio de la spec 007 si hace falta",
        )
        for entry in entries
    ]


def _finding(message: str) -> Finding:
    return Finding(EXTENSION_DIR, 0, RULE_EXTENSION_DIR, message)


def _has_py(folder: Path) -> bool:
    for _current, _dirs, files in os.walk(folder):
        if any(name.endswith(".py") for name in files):
            return True
    return False


def check_extension_dir(root: Path) -> list[Finding]:
    """REP-02: la carpeta de la extensión, con su nombre exacto, el manifiesto y algún
    ``.py``."""
    names = os.listdir(root)
    if EXTENSION_DIR not in names:
        others = sorted(
            name for name in names if name.casefold() == EXTENSION_DIR.casefold()
        )
        if others:
            return [
                _finding(
                    f"la carpeta de la extensión se llama «{others[0]}» y debe llamarse "
                    f"«{EXTENSION_DIR}», mayúsculas incluidas: renómbrela en dos pasos "
                    "(git mv a un nombre temporal y después al definitivo)"
                )
            ]
        return [_finding(f"falta la carpeta de la extensión «{EXTENSION_DIR}» en la raíz")]
    folder = Path(root) / EXTENSION_DIR
    if not folder.is_dir():
        return [_finding(f"«{EXTENSION_DIR}» debe ser la carpeta de la extensión")]
    findings: list[Finding] = []
    if not (Path(root) / MANIFEST_RELPATH).is_file():
        findings.append(
            _finding(
                f"la carpeta de la extensión «{EXTENSION_DIR}» no tiene el manifiesto "
                f"«{MANIFEST_RELPATH.rsplit('/', 1)[-1]}»"
            )
        )
    if not _has_py(folder):
        findings.append(
            _finding(f"la carpeta de la extensión «{EXTENSION_DIR}» no tiene ningún .py")
        )
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de REP-01 y REP-02 en ``root``."""
    return sorted(check_root_entries(root) + check_extension_dir(root))
