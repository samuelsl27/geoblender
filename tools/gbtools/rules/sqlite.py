# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-17: SQLite nunca en WAL (spec 002, T06; RF-002-16; ADR-0006; vision-general §10).

El modo WAL de SQLite no funciona en un sistema de ficheros en red y los proyectos de IMGA
viven en una unidad de red: el GeoPackage del proyecto va siempre en diario clásico.

En todo ``geoblender/``: un literal de cadena (salvo los docstrings), o una parte literal
de una f-string, que pone ``journal_mode`` en WAL (``PRAGMA journal_mode=WAL``, con o sin
esquema, espacios, comillas o punto y coma, en cualquier combinación de mayúsculas). La
palabra suelta no cuenta: una cabecera que dice «wal» es un dato, no una orden. Las
pruebas que necesitan una base en WAL para simular a QGIS la preparan en ``tests/``.

Límite declarado: no ve el modo cuando llega por otro camino (``f"… journal_mode={m}"``
con ``m`` igual a WAL, o dos literales que se concatenan al ejecutar); lo cubren las
pruebas de ``core.gpkg`` (``journal_mode`` = ``delete`` tras cada transacción).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..findings import Finding
from ..layout import EXTENSION_DIR
from . import pyast

RULE = "ARQ-17"
EXTENSION = EXTENSION_DIR
_WITH_DOCSTRING = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
WAL_LITERAL = re.compile(r"journal_mode\s*=\s*['\"]?\s*wal\b", re.IGNORECASE)


def _docstrings(tree: ast.Module) -> set[int]:
    """``id`` de los literales que son docstrings (módulo, clases y funciones)."""
    found: set[int] = set()
    for node in pyast.nodes_of(tree, _WITH_DOCSTRING):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    return found


def module_findings(module: pyast.PyModule) -> list[Finding]:
    """Incumplimientos de ARQ-17 en un módulo analizado."""
    skip = _docstrings(module.tree)
    lines: set[int] = set()
    for node in pyast.nodes_of(module.tree, ast.Constant):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and WAL_LITERAL.search(node.value)
        ):
            lines.add(node.lineno)
    return [
        Finding(
            module.rel,
            line,
            RULE,
            "pone SQLite en modo WAL, que no funciona en una unidad de red: el "
            "GeoPackage del proyecto va siempre en diario clásico (journal_mode = "
            "DELETE; ADR-0006)",
        )
        for line in sorted(lines)
    ]


def check(root: Path) -> list[Finding]:
    """Incumplimientos de ARQ-17 en ``geoblender/`` (y AST-01)."""
    modules, findings = pyast.parse_modules(root, EXTENSION, EXTENSION)
    for module in modules:
        findings.extend(module_findings(module))
    return sorted(findings)
