# SPDX-License-Identifier: GPL-3.0-or-later
"""AGT-01 y AGT-02: ficheros de instrucciones de los agentes (RF-001-21).

- AGT-01: cada ``AGENTS.md`` tiene al lado un ``CLAUDE.md`` cuyo único contenido es
  ``@AGENTS.md`` (con o sin salto final), y cada ``CLAUDE.md`` tiene su ``AGENTS.md``.
  Claude Code no lee ``AGENTS.md`` si existe un ``CLAUDE.md``: el puntero lo importa.
- AGT-02: el ``AGENTS.md`` raíz, como mucho 200 líneas y 16 384 bytes; uno anidado,
  como mucho 120 líneas. Por encima baja la adherencia (docs/trampas.md §8).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..findings import Finding
from ..repo import ALWAYS_EXCLUDED, iter_repo_files, relpath

RULE_POINTER = "AGT-01"
RULE_SIZE = "AGT-02"
AGENTS = "AGENTS.md"
CLAUDE = "CLAUDE.md"
POINTER_CONTENTS: frozenset[bytes] = frozenset(
    {b"@AGENTS.md", b"@AGENTS.md\n", b"@AGENTS.md\r\n"}
)
ROOT_MAX_LINES = 200
ROOT_MAX_BYTES = 16_384
NESTED_MAX_LINES = 120


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
        "lleve el detalle a docs/trampas.md y deje en AGENTS.md como mucho una línea "
        "por trampa"
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
                    "sin él, Claude Code no lee estas reglas (docs/trampas.md §8)",
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
