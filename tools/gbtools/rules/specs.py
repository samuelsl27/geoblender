# SPDX-License-Identifier: GPL-3.0-or-later
"""NOM-03: carpetas de ``specs/`` (ADR-0011; RF-001-17).

Cada carpeta de ``specs/`` (salvo ``_plantillas``) se llama ``NNN-<código>-<slug>`` y su
número no se repite. Los códigos de módulo son los de ``naming.MODULE_CODES``
(``convenciones.md`` §5 de la documentación).

Es una regla de la documentación (spec 007, RF-007-11): la ejecuta
``tools/check_docs.py`` (``DOCS_FAMILIES``), no el verde del código.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..findings import Finding
from .naming import MODULE_CODES

RULE = "NOM-03"
SPECS_DIR = "specs"
SPECS_EXEMPT: frozenset[str] = frozenset({"_plantillas"})
SPEC_RE = re.compile(rf"^(\d{{3}})-({'|'.join(MODULE_CODES)})-[a-z0-9-]+$")


def check(root: Path) -> list[Finding]:
    """Incumplimientos de NOM-03 en ``specs/`` de ``root`` (ninguno si no existe)."""
    specs = Path(root) / SPECS_DIR
    if not specs.is_dir():
        return []
    with os.scandir(specs) as scan:
        folders = sorted(
            entry.name
            for entry in scan
            if entry.is_dir(follow_symlinks=False) and entry.name not in SPECS_EXEMPT
        )
    findings: list[Finding] = []
    by_number: dict[str, list[str]] = {}
    for name in folders:
        match = SPEC_RE.match(name)
        if match is None:
            findings.append(
                Finding(
                    f"{SPECS_DIR}/{name}",
                    0,
                    RULE,
                    "la carpeta de una spec se llama NNN-<código>-<slug> (tres cifras, "
                    "un código de módulo y un slug en minúsculas; ADR-0011)",
                )
            )
            continue
        by_number.setdefault(match.group(1), []).append(name)
    for number, names in by_number.items():
        if len(names) > 1:
            for name in names:
                others = ", ".join(other for other in names if other != name)
                findings.append(
                    Finding(
                        f"{SPECS_DIR}/{name}",
                        0,
                        RULE,
                        f"el número {number} se repite en {others}: los números de "
                        "spec son únicos y no se reutilizan",
                    )
                )
    return sorted(findings)
