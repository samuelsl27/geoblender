# SPDX-License-Identifier: GPL-3.0-or-later
"""TXT-01 a TXT-03: codificación, finales de línea y enlaces (RF-001-19).

- TXT-01: un fichero de texto que no es UTF-8 estricto o que empieza por BOM.
- TXT-02: un fichero de texto con algún ``\\r``; si es ``.ps1``, ``.bat`` o ``.cmd``,
  algún ``\\n`` sin ``\\r`` delante. Los textos de licencia (``LICENSE``,
  ``LICENSES/`` y los ``LICENSE`` de las carpetas de activos) quedan fuera: su
  contenido lo comprueban LIC-03 y LIC-04.
- TXT-03: un enlace simbólico o un punto de reparación (el repositorio vive en un
  recurso SMB y git tiene ``core.symlinks=false``).

«Fichero de texto» es todo lo que no tiene una extensión binaria de ``.gitattributes``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path

from ..findings import Finding
from ..layout import ASSET_ROOTS
from ..repo import ALWAYS_EXCLUDED, is_text_file, iter_repo_files, read_bytes, relpath

RULE_ENCODING = "TXT-01"
RULE_LINE_ENDINGS = "TXT-02"
RULE_LINKS = "TXT-03"

BOM = b"\xef\xbb\xbf"
CRLF_SUFFIXES: frozenset[str] = frozenset({".ps1", ".bat", ".cmd"})
# ASSET_ROOTS (gbtools.layout): carpetas de activos cuyo LICENSE es una copia de
# LICENSES/CC0-1.0.txt (plan 001 §5.2).
_BARE_LF = re.compile(rb"(?<!\r)\n")


def line_endings_exempt(rel: str) -> bool:
    """Verdadero para los textos de licencia, que conservan sus finales de línea."""
    if rel == "LICENSE" or rel.startswith("LICENSES/"):
        return True
    return rel.rsplit("/", 1)[-1] == "LICENSE" and rel.startswith(ASSET_ROOTS)


def _line_of(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def _encoding(rel: str, data: bytes) -> list[Finding]:
    findings: list[Finding] = []
    if data.startswith(BOM):
        findings.append(
            Finding(
                rel,
                1,
                RULE_ENCODING,
                "empieza por BOM (EF BB BF): guárdelo en UTF-8 sin BOM",
            )
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        byte = data[exc.start]
        findings.append(
            Finding(
                rel,
                _line_of(data, exc.start),
                RULE_ENCODING,
                f"no es UTF-8 válido (byte 0x{byte:02X} en la posición {exc.start}; "
                "¿Latin-1 o OEM 850?): guárdelo en UTF-8 sin BOM",
            )
        )
    return findings


def _line_endings(rel: str, data: bytes) -> list[Finding]:
    if line_endings_exempt(rel):
        return []
    suffix = Path(rel).suffix.lower()
    if suffix in CRLF_SUFFIXES:
        bare = _BARE_LF.search(data)
        if bare is None:
            return []
        message = (
            f"es un guion de Windows ({suffix}) con finales LF: guárdelo con finales "
            "CRLF (.gitattributes)"
        )
        return [Finding(rel, _line_of(data, bare.start()), RULE_LINE_ENDINGS, message)]
    first_cr = data.find(b"\r")
    if first_cr < 0:
        return []
    carriage_returns = data.count(b"\r")
    message = (
        f"tiene finales CRLF o CR sueltos ({carriage_returns} «\\r»): guárdelo con "
        "finales LF (.gitattributes, .editorconfig)"
    )
    return [Finding(rel, _line_of(data, first_cr), RULE_LINE_ENDINGS, message)]


def check(root: Path, excluded: Sequence[str] = ALWAYS_EXCLUDED) -> list[Finding]:
    """Incumplimientos de TXT-01, TXT-02 y TXT-03 en el repositorio comprobado (sin
    las carpetas ``excluded`` de la raíz: ``iter_repo_files``)."""
    findings: list[Finding] = []
    for path in iter_repo_files(root, excluded):
        rel = relpath(root, path)
        if path.is_symlink() or os.path.isjunction(path):
            findings.append(
                Finding(
                    rel,
                    0,
                    RULE_LINKS,
                    "es un enlace simbólico o un punto de reparación: el repositorio "
                    "vive en un recurso SMB y git no los conserva; use un fichero "
                    "normal o un puntero como CLAUDE.md (AGENTS.md, regla 11)",
                )
            )
            continue
        if not is_text_file(path):
            continue
        data = read_bytes(path)
        findings.extend(_encoding(rel, data))
        findings.extend(_line_endings(rel, data))
    return sorted(findings)
