# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-14: la conversión absoluta ↔ local solo existe en ``core.georef.transform``
(spec 002, T04; RF-002-25; ADR-0005; vision-general §10, ratificada en el plan 001, D-2).

En todo ``geoblender/`` salvo ``core/georef/transform.py`` (``ALLOWED_MODULE``), una resta
o una suma (``a - b``, ``a + b``, ``a -= b``, ``a += b``) en la que uno de los dos
operandos contiene una referencia al GeoOrigin:

- un atributo ``x0``, ``y0``, ``z0``, ``origin_x``, ``origin_y`` u ``origin_z``
  (``origin.x0``, ``scene.geoblender.origin_y``);
- un nombre con esos mismos identificadores (``z0``).

La referencia cuenta también dentro de la expresión que se resta o se suma
(``xyz - np.array([origin.x0, origin.y0, origin.z0])``). Restar el origen es pasar a
locales, y sumarlo, volver a absolutas: los dos sentidos tienen que pasar por
``world_to_local`` y ``local_to_world``, que trabajan en float64 y tienen sus pruebas de
ida y vuelta (≤ 0,5 mm a ±8 km). Un incumplimiento por línea.

Límite declarado: no ve el origen cuando llega con otro nombre (``offset = origin.x0`` y
después ``x - offset``) ni dentro de una función a la que se llama; lo cubren las pruebas
de ida y vuelta de la spec 002 (T04 y T29) y la revisión del código.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..findings import Finding
from ..layout import EXTENSION_DIR
from . import pyast

RULE = "ARQ-14"
EXTENSION = EXTENSION_DIR
ALLOWED_MODULE = "core/georef/transform.py"  # relativo a la extensión
ORIGIN_IDENTIFIERS: frozenset[str] = frozenset(
    {"x0", "y0", "z0", "origin_x", "origin_y", "origin_z"}
)
_OPERATORS = (ast.Sub, ast.Add)


def _refers_to_origin(node: ast.AST) -> bool:
    """Verdadero si la expresión contiene un atributo o un nombre del GeoOrigin."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in ORIGIN_IDENTIFIERS:
            return True
        if isinstance(child, ast.Name) and child.id in ORIGIN_IDENTIFIERS:
            return True
    return False


def _operands(node: ast.AST) -> tuple[ast.AST, ...] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, _OPERATORS):
        return (node.left, node.right)
    if isinstance(node, ast.AugAssign) and isinstance(node.op, _OPERATORS):
        return (node.target, node.value)
    return None


def module_findings(module: pyast.PyModule) -> list[Finding]:
    """Incumplimientos de ARQ-14 en un módulo analizado."""
    lines: set[int] = set()
    for node in ast.walk(module.tree):
        operands = _operands(node)
        if operands is not None and any(_refers_to_origin(side) for side in operands):
            lines.add(node.lineno)
    return [
        Finding(
            module.rel,
            line,
            RULE,
            "resta o suma el GeoOrigin fuera de core.georef.transform: pase a locales "
            "con world_to_local y vuelva a absolutas con local_to_world, en float64 "
            "(ADR-0005; la conversión vive en un único sitio, con sus pruebas de ida y "
            "vuelta)",
        )
        for line in sorted(lines)
    ]


def check(root: Path) -> list[Finding]:
    """Incumplimientos de ARQ-14 en ``geoblender/`` (y AST-01)."""
    modules, findings = pyast.parse_modules(root, EXTENSION, EXTENSION)
    allowed = f"{EXTENSION}/{ALLOWED_MODULE}"
    for module in modules:
        if module.rel != allowed:
            findings.extend(module_findings(module))
    return sorted(findings)
