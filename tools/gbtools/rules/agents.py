# SPDX-License-Identifier: GPL-3.0-or-later
"""AGT-01, AGT-02 y AGT-03: ficheros de instrucciones de los agentes (RF-001-21,
RF-007-05).

- AGT-01: cada ``AGENTS.md`` tiene al lado un ``CLAUDE.md`` cuyo único contenido es
  ``@AGENTS.md`` (con o sin salto final), y cada ``CLAUDE.md`` tiene su ``AGENTS.md``.
  Claude Code no lee ``AGENTS.md`` si existe un ``CLAUDE.md``: el puntero lo importa.
- AGT-02: el ``AGENTS.md`` raíz, como mucho 200 líneas y 16 384 bytes; uno anidado,
  como mucho 120 líneas. Por encima baja la adherencia (``docs/trampas.md`` §8 de la
  documentación).
- AGT-03, solo en el repositorio de código (spec 007): su ``AGENTS.md`` raíz es el
  mínimo de la decisión (ADR-0023): existe, nombra ``GEOBLENDER_DOCS_DIR`` (dónde está
  la documentación si no es la carpeta madre) y tiene como mucho 60 líneas. La guía
  completa está en el ``AGENTS.md`` de la documentación.

:func:`check` (AGT-01 y AGT-02) sirve para los dos repositorios; :func:`check_code`, la
familia del código, añade AGT-03. Los mensajes citan las rutas de la documentación como
«de la documentación»: el código no tiene ``docs/``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from ..findings import Finding
from ..layout import CODE_AGENTS_MAX_LINES, ENV_DOCS_DIR
from ..repo import ALWAYS_EXCLUDED, iter_repo_files, relpath

RULE_POINTER = "AGT-01"
RULE_SIZE = "AGT-02"
RULE_CODE_AGENTS = "AGT-03"
AGENTS = "AGENTS.md"
CLAUDE = "CLAUDE.md"
POINTER_CONTENTS: frozenset[bytes] = frozenset(
    {b"@AGENTS.md", b"@AGENTS.md\n", b"@AGENTS.md\r\n"}
)
ROOT_MAX_LINES = 200
ROOT_MAX_BYTES = 16_384
NESTED_MAX_LINES = 120
TRAPS = "docs/trampas.md de la documentación"


def count_lines(data: bytes) -> int:
    """Líneas de un texto, cuente o no con salto final."""
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _size_findings(rel: str, data: bytes, nested: bool) -> list[Finding]:
    lines = count_lines(data)
    limit = NESTED_MAX_LINES if nested else ROOT_MAX_LINES
    where = "anidado" if nested else "raíz"
    advice = (
        f"lleve el detalle a {TRAPS} y deje en AGENTS.md como mucho una línea por "
        "trampa"
    )
    findings: list[Finding] = []
    if lines > limit:
        findings.append(
            Finding(
                rel,
                0,
                RULE_SIZE,
                f"tiene {lines} líneas y un AGENTS.md {where} admite {limit}: {advice}",
            )
        )
    if not nested and len(data) > ROOT_MAX_BYTES:
        findings.append(
            Finding(
                rel,
                0,
                RULE_SIZE,
                f"ocupa {len(data)} bytes y el AGENTS.md raíz admite {ROOT_MAX_BYTES}: "
                f"{advice}",
            )
        )
    return findings


def check(root: Path, excluded: Sequence[str] = ALWAYS_EXCLUDED) -> list[Finding]:
    """Incumplimientos de AGT-01 y AGT-02 en el repositorio comprobado (sin las
    carpetas ``excluded`` de la raíz: ``iter_repo_files``)."""
    agents: dict[str, Path] = {}
    claudes: dict[str, Path] = {}
    for path in iter_repo_files(root, excluded):
        folder = relpath(root, path).rpartition("/")[0]  # "" en la raíz
        if path.name == AGENTS:
            agents[folder] = path
        elif path.name == CLAUDE:
            claudes[folder] = path
    findings: list[Finding] = []
    for folder, path in agents.items():
        rel = relpath(root, path)
        if folder not in claudes:
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_POINTER,
                    "falta un CLAUDE.md al lado con una sola línea «@AGENTS.md»: "
                    f"sin él, Claude Code no lee estas reglas ({TRAPS}, §8)",
                )
            )
        if not path.is_symlink():
            findings.extend(_size_findings(rel, path.read_bytes(), nested=bool(folder)))
    for folder, path in claudes.items():
        rel = relpath(root, path)
        if folder not in agents:
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_POINTER,
                    "CLAUDE.md sin AGENTS.md al lado: las reglas van en un AGENTS.md y "
                    "CLAUDE.md solo lo importa",
                )
            )
        if not path.is_symlink() and path.read_bytes() not in POINTER_CONTENTS:
            findings.append(
                Finding(
                    rel,
                    1,
                    RULE_POINTER,
                    "su único contenido debe ser «@AGENTS.md»: las reglas van en "
                    "AGENTS.md, no en CLAUDE.md",
                )
            )
    return sorted(findings)


def check_code_agents(root: Path) -> list[Finding]:
    """AGT-03: el ``AGENTS.md`` raíz del repositorio de código existe (con ese nombre
    exacto), nombra ``GEOBLENDER_DOCS_DIR`` y tiene como mucho 60 líneas."""
    if AGENTS not in os.listdir(root):
        return [
            Finding(
                AGENTS,
                0,
                RULE_CODE_AGENTS,
                "falta el AGENTS.md mínimo del repositorio de código: dice que la "
                f"documentación está en la carpeta madre o en {ENV_DOCS_DIR}, y qué "
                "leer allí antes de cualquier tarea (spec 007, RF-007-05)",
            )
        ]
    path = Path(root) / AGENTS
    if path.is_symlink():
        return []  # un enlace simbólico lo señala TXT-03
    if not path.is_file():
        return [
            Finding(AGENTS, 0, RULE_CODE_AGENTS, "AGENTS.md debe ser un fichero de texto")
        ]
    data = path.read_bytes()
    findings: list[Finding] = []
    if ENV_DOCS_DIR.encode("ascii") not in data:
        findings.append(
            Finding(
                AGENTS,
                0,
                RULE_CODE_AGENTS,
                f"no nombra {ENV_DOCS_DIR}: el AGENTS.md mínimo del código dice que la "
                "documentación está en la carpeta madre o en esa variable, sin escribir "
                "su ruta (spec 007, RF-007-05)",
            )
        )
    lines = count_lines(data)
    if lines > CODE_AGENTS_MAX_LINES:
        findings.append(
            Finding(
                AGENTS,
                0,
                RULE_CODE_AGENTS,
                f"tiene {lines} líneas y el AGENTS.md mínimo del código admite "
                f"{CODE_AGENTS_MAX_LINES}: la guía completa de los agentes es el "
                "AGENTS.md de la documentación (spec 007, RF-007-05)",
            )
        )
    return findings


def check_code(root: Path) -> list[Finding]:
    """La familia del repositorio de código: AGT-01, AGT-02 y AGT-03."""
    return sorted(check(root) + check_code_agents(root))
