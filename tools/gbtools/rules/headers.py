# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-12: cabecera SPDX de cada ``.py`` (ADR-0002; RF-001-18).

La primera línea (la segunda si la primera empieza por ``#!``) debe ser exactamente
``# SPDX-License-Identifier: GPL-3.0-or-later``. Un BOM delante no cuenta aquí: lo
señala TXT-01.
"""

from __future__ import annotations

from pathlib import Path

from ..findings import Finding
from ..repo import iter_py_files, read_bytes, relpath

RULE = "ARQ-12"
HEADER = "# SPDX-License-Identifier: GPL-3.0-or-later"


def header_problem(data: bytes) -> tuple[int, str] | None:
    """``(línea, mensaje)`` si a un ``.py`` le falta la cabecera; si no, ``None``."""
    text = data.decode("utf-8", errors="replace").removeprefix("﻿")
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    expected = 2 if lines[0].startswith("#!") else 1
    if len(lines) >= expected and lines[expected - 1] == HEADER:
        return None
    where = "segunda línea, tras el «#!»" if expected == 2 else "primera línea"
    message = f"falta la cabecera «{HEADER}» en la {where}"
    if HEADER in lines:
        message += f" (está en la línea {lines.index(HEADER) + 1}; súbala)"
    return expected, message


def check(root: Path) -> list[Finding]:
    """Incumplimientos de ARQ-12 en los ``.py`` del repositorio comprobado."""
    findings: list[Finding] = []
    for path in iter_py_files(root):
        if path.is_symlink():
            continue  # lo señala TXT-03
        problem = header_problem(read_bytes(path))
        if problem is not None:
            line, message = problem
            findings.append(Finding(relpath(root, path), line, RULE, message))
    return findings
