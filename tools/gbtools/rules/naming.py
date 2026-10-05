# SPDX-License-Identifier: GPL-3.0-or-later
"""NOM-01 y NOM-02: nombres de ADR-0011 (RF-001-17); NOM-03, en ``rules.specs``; NOM-04,
en ``gbtools.manifest``.

- NOM-01: una clase de ``geoblender/bl/`` cuya base termina en ``Operator``, ``Panel``,
  ``Menu``, ``PropertyGroup`` o ``UIList`` se llama
  ``GEOBLENDER_<OT|PT|MT|PG|UL>_<código>_<acción>`` (en minúsculas tras el código).
- NOM-02: el ``bl_idname`` literal de un operador casa
  ``geoblender.<código>_<acción>`` y es
  ``"geoblender." + clase[len("GEOBLENDER_OT_"):].lower()``.

Los códigos de módulo son los de ``docs/sdd/convenciones.md`` §5.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..findings import Finding
from ..layout import EXTENSION_DIR
from . import pyast

RULE_CLASS = "NOM-01"
RULE_IDNAME = "NOM-02"

MODULE_CODES: tuple[str, ...] = (
    "core",
    "ui",
    "jobs",
    "gis",
    "dh",
    "geo",
    "imp",
    "bm",
    "opt",
    "des",
    "res",
    "plan",
    "io",
)
_CODES = "|".join(MODULE_CODES)
CLASS_RE = re.compile(rf"^GEOBLENDER_(OT|PT|MT|PG|UL)_({_CODES})_[a-z0-9_]+$")
IDNAME_RE = re.compile(rf"^geoblender\.({_CODES})_[a-z0-9_]+$")
BLENDER_BASES: tuple[str, ...] = (
    "Operator",
    "Panel",
    "Menu",
    "PropertyGroup",
    "UIList",
)
OPERATOR_PREFIX = "GEOBLENDER_OT_"
BL_DIR = f"{EXTENSION_DIR}/bl/"


def _bases(node: ast.ClassDef) -> list[str]:
    return [ast.unparse(base) for base in node.bases]


def _literal_idname(node: ast.ClassDef) -> tuple[int, str] | None:
    for statement in node.body:
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "bl_idname"
            for target in statement.targets
        ):
            value = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "bl_idname"
        ):
            value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return statement.lineno, value.value
    return None


def _class_findings(module: pyast.PyModule) -> list[Finding]:
    findings: list[Finding] = []
    for node in pyast.iter_statements(module.tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = _bases(node)
        if not any(base.endswith(BLENDER_BASES) for base in bases):
            continue
        if not CLASS_RE.match(node.name):
            findings.append(
                Finding(
                    module.rel,
                    node.lineno,
                    RULE_CLASS,
                    f"la clase «{node.name}» debe llamarse "
                    "GEOBLENDER_<OT|PT|MT|PG|UL>_<código>_<acción>, con un código de "
                    "módulo (core, ui, dh…) y la acción en minúsculas (ADR-0011)",
                )
            )
        if not any(base.endswith("Operator") for base in bases):
            continue
        idname = _literal_idname(node)
        if idname is None:
            continue
        line, value = idname
        expected = "geoblender." + node.name[len(OPERATOR_PREFIX) :].lower()
        if not IDNAME_RE.match(value) or value != expected:
            findings.append(
                Finding(
                    module.rel,
                    line,
                    RULE_IDNAME,
                    f"bl_idname «{value}» no corresponde a la clase «{node.name}»: "
                    f"debe ser «{expected}» (geoblender.<código>_<acción>; "
                    "ADR-0011)",
                )
            )
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de NOM-01, NOM-02 (en ``geoblender/bl/``) y AST-01."""
    modules, findings = pyast.parse_modules(root, BL_DIR.rstrip("/"), EXTENSION_DIR)
    for module in modules:
        findings.extend(_class_findings(module))
    return sorted(findings)
