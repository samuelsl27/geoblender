# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-13: GeoOrigin en enteros y sin propiedades flotantes de coordenadas absolutas.

ADR-0005; RF-001-15. En todo ``geoblender/`` (no solo ``bl/props/``):

(a) una anotación o asignación cuyo destino (nombre o atributo) es ``origin_x``,
    ``origin_y`` u ``origin_z`` y cuyo valor es una llamada a ``…Property`` distinta de
    ``IntProperty``;
(b) una llamada a ``FloatProperty`` o ``FloatVectorProperty`` (por nombre o atributo)
    anotada o asignada a un destino cuyo nombre, en minúsculas y partido por «_»,
    contiene un término de ``ABS_COORD_TOKENS``.

El tipo de la propiedad se reconoce también con otro nombre: importado con ``as``
(``from bpy.props import FloatVectorProperty as Vec3``) o asignado a un nombre en el
fichero (``Real = bpy.props.FloatProperty``), antes de la llamada (convergencia de la
spec 001, T52). Entre los términos están también los de la boca de un sondeo y las
coordenadas de un punto, ``collar``, ``coord``, ``coords`` y ``xyz`` (``collar:
FloatVectorProperty(size=3)`` guardaría en float32 la boca en UTM; T58), y los de la cota,
``level``, ``cota`` y ``elev`` (``dest_level: FloatProperty()``; spec 017, T45).

Límite declarado: no ve propiedades creadas con ``setattr`` o diccionarios (las
cubren las pruebas de ida y vuelta de la spec 002), ni un tipo que llega por otro
camino (una función que lo devuelve, un alias definido en otro módulo).
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..findings import Finding
from ..layout import EXTENSION_DIR
from . import pyast

RULE = "ARQ-13"
EXTENSION = EXTENSION_DIR
ORIGIN_NAMES: frozenset[str] = frozenset({"origin_x", "origin_y", "origin_z"})
ABS_COORD_TOKENS: frozenset[str] = frozenset(
    {
        "origin",
        "x0",
        "y0",
        "z0",
        "easting",
        "northing",
        "utm",
        "abs",
        "absolute",
        "world",
        "georef",
        # La boca de un sondeo y las coordenadas de un punto (spec 005; convergencia de
        # la spec 001, T58).
        "collar",
        "coord",
        "coords",
        "xyz",
        # La cota: ninguna propiedad es una coordenada ni una cota en ``FloatProperty``
        # (ADR-0005); verificación única de la spec 017, T45 (hallazgo E-5): nada de
        # ``geoblender/`` las usa hoy con un flotante.
        "level",
        "cota",
        "elev",
    }
)
FLOAT_PROPERTIES: frozenset[str] = frozenset({"FloatProperty", "FloatVectorProperty"})


def has_abs_coord_token(name: str) -> bool:
    """Verdadero si algún trozo de ``name`` (por «_», en minúsculas) es un término de
    coordenada absoluta."""
    return not ABS_COORD_TOKENS.isdisjoint(name.lower().split("_"))


def _callee(node: ast.expr | None, aliases: dict[str, str]) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Otros nombres de un tipo de propiedad en el fichero: ``from … import
    FloatProperty as F`` y ``F = bpy.props.FloatProperty`` (o ``= FloatProperty``, o
    ``= otro_alias``), en el orden del fichero → ``{"F": "FloatProperty"}``."""
    aliases: dict[str, str] = {}
    for node in pyast.iter_statements(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.name.endswith("Property"):
                    aliases[alias.asname] = alias.name
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = _target_name(node.value)
            if name is not None and isinstance(node.value, ast.Name):
                name = aliases.get(name, name)
            if name is not None and name.endswith("Property"):
                aliases[node.targets[0].id] = name
    return aliases


def _target_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _problem(name: str, callee: str) -> str | None:
    if not callee.endswith("Property"):
        return None
    if name in ORIGIN_NAMES and callee != "IntProperty":
        return (
            f"«{name}» es una coordenada del GeoOrigin y usa {callee}: debe ser "
            "IntProperty en metros enteros (ADR-0005)"
        )
    if callee in FLOAT_PROPERTIES and has_abs_coord_token(name):
        return (
            f"«{name}» parece una coordenada absoluta y usa {callee} (float32, con "
            "nortes UTM la resolución es de 0,5 m): use coordenadas locales respecto "
            "al GeoOrigin o IntProperty, o renombre la propiedad (ADR-0005)"
        )
    return None


def module_findings(module: pyast.PyModule) -> list[Finding]:
    """Incumplimientos de ARQ-13 en un módulo analizado."""
    findings: list[Finding] = []
    aliases = _aliases(module.tree)
    for node in pyast.iter_statements(module.tree):
        pairs: list[tuple[ast.expr, ast.expr | None]] = []
        if isinstance(node, ast.AnnAssign):
            pairs = [(node.target, node.annotation), (node.target, node.value)]
        elif isinstance(node, ast.Assign):
            pairs = [(target, node.value) for target in node.targets]
        reported = False
        for target, value in pairs:
            name, callee = _target_name(target), _callee(value, aliases)
            if reported or name is None or callee is None:
                continue
            message = _problem(name, callee)
            if message is not None:
                findings.append(Finding(module.rel, node.lineno, RULE, message))
                reported = True
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de ARQ-13 en ``geoblender/`` (y AST-01)."""
    modules, findings = pyast.parse_modules(root, EXTENSION, EXTENSION)
    for module in modules:
        findings.extend(module_findings(module))
    return sorted(findings)
